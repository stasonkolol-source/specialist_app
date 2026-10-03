"""Жалобы (DEVELOPMENT_PLAN 4.7): жалоба — повод кейса P1 или P0, повтор, пока кейс открыт, — та же
жалоба, лимит в сутки, решение по кейсу закрывает жалобы.

Use cases на PostgreSQL в откатываемой транзакции; на кого жалоба и лимит — фейки (ADR-0020 §11).
Сквозной путь через HTTP, настоящие фасады и Valkey — tests/integration/test_reports_and_blocks.py.
"""

from uuid import UUID

import pytest

from app.modules.moderation.application.use_cases.create_report import CreateReportCommand
from app.modules.moderation.application.use_cases.decide_case import DecideCaseCommand
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportReason, ReportStatus
from app.modules.moderation.errors import (
    InvalidReportError,
    ReportsLimitError,
    ReportTargetNotFoundError,
)
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import UserId, new_id

from .conftest import Moderation

pytestmark = pytest.mark.integration


def report(
    reporter: UserId,
    target: UUID,
    reason: ReportReason = ReportReason.FRAUD,
    *,
    target_type: EntityType = EntityType.PROFILE,
    **fields: object,
) -> CreateReportCommand:
    return CreateReportCommand(
        reporter_id=reporter,
        target_type=target_type,
        target_id=target,
        reason=reason,
        **fields,  # type: ignore[arg-type]
    )


async def test_report_opens_a_case_about_the_author(moderation: Moderation) -> None:
    reporter, author = await moderation.user(), await moderation.user()
    profile = new_id()
    moderation.report_targets.authors[profile] = author

    filed = await moderation.report(
        report(reporter, profile, comment="  Попросил перевести 2 000 RSD на карту  ")
    )

    assert (filed.created, filed.queue) == (True, Queue.FRAUD)
    [(queue, subject, trigger, signals)] = await moderation.rows(
        "SELECT queue, subject_id, trigger, evidence -> 0 -> 'signals' FROM moderation.cases"
        " WHERE entity_id = :id",
        id=profile,
    )
    assert (queue, subject, trigger, signals) == ("fraud", author, "report", ["report:fraud"])
    [(comment, status, case_id)] = await moderation.rows(
        "SELECT comment, status, case_id FROM moderation.reports WHERE id = :id",
        id=filed.report.id,
    )
    assert (comment, status, case_id) == (
        "Попросил перевести 2 000 RSD на карту",
        "open",
        filed.report.case_id,
    )


async def test_threats_go_to_p0_and_join_the_open_case(moderation: Moderation) -> None:
    author = await moderation.user()
    profile = new_id()
    moderation.report_targets.authors[profile] = author
    first = await moderation.report(report(await moderation.user(), profile))

    second = await moderation.report(
        report(await moderation.user(), profile, ReportReason.OFFENSIVE)
    )

    assert second.queue is Queue.SAFETY
    assert second.report.case_id == first.report.case_id
    [(queue, triggers)] = await moderation.rows(
        "SELECT queue, jsonb_array_length(evidence) FROM moderation.cases WHERE entity_id = :id",
        id=profile,
    )
    assert (queue, triggers) == ("safety", 2)


async def test_repeat_while_the_case_is_open_is_the_same_report(moderation: Moderation) -> None:
    reporter, author = await moderation.user(), await moderation.user()
    job = new_id()
    moderation.report_targets.authors[job] = author
    first = await moderation.report(report(reporter, job, target_type=EntityType.JOB))

    again = await moderation.report(
        report(reporter, job, ReportReason.SPAM, target_type=EntityType.JOB)
    )

    assert (again.created, again.report.id, again.report.reason) == (
        False,
        first.report.id,
        ReportReason.FRAUD,
    )
    assert moderation.report_quota.taken[reporter] == 1
    [(triggers,)] = await moderation.rows(
        "SELECT jsonb_array_length(evidence) FROM moderation.cases WHERE entity_id = :id", id=job
    )
    assert triggers == 1


async def test_decision_closes_reports_and_a_new_report_counts_again(
    moderation: Moderation,
) -> None:
    reporter, author = await moderation.user(), await moderation.user()
    profile = new_id()
    moderation.report_targets.authors[profile] = author
    filed = await moderation.report(report(reporter, profile))
    assert filed.report.case_id is not None

    await moderation.decide(
        DecideCaseCommand(
            case_id=filed.report.case_id,
            verdict=ModerationDecision.REJECTED,
            reason_code="prepayment_scam",
        )
    )
    [(status, resolution)] = await moderation.rows(
        "SELECT status, resolution FROM moderation.reports WHERE id = :id", id=filed.report.id
    )
    assert (status, resolution) == (ReportStatus.RESOLVED.value, "prepayment_scam")
    assert moderation.identity.violations == [author]  # подтверждённая жалоба

    again = await moderation.report(report(reporter, profile))
    assert again.created
    assert again.report.case_id != filed.report.case_id


async def test_dismissed_case_rejects_its_reports(moderation: Moderation) -> None:
    author = await moderation.user()
    profile = new_id()
    moderation.report_targets.authors[profile] = author
    filed = await moderation.report(report(await moderation.user(), profile))
    assert filed.report.case_id is not None

    await moderation.decide(
        DecideCaseCommand(case_id=filed.report.case_id, verdict=ModerationDecision.APPROVED)
    )

    [(status,)] = await moderation.rows(
        "SELECT status FROM moderation.reports WHERE id = :id", id=filed.report.id
    )
    assert status == ReportStatus.REJECTED.value
    assert moderation.identity.violations == []


async def test_twenty_first_report_a_day_is_refused(moderation: Moderation) -> None:
    reporter, author = await moderation.user(), await moderation.user()
    for _ in range(20):
        target = new_id()
        moderation.report_targets.authors[target] = author
        await moderation.report(report(reporter, target))
    target = new_id()
    moderation.report_targets.authors[target] = author

    with pytest.raises(ReportsLimitError):
        await moderation.report(report(reporter, target))
    assert (
        await moderation.rows("SELECT 1 FROM moderation.reports WHERE target_id = :id", id=target)
        == []
    )


async def test_what_cannot_be_reported(moderation: Moderation) -> None:
    reporter, author = await moderation.user(), await moderation.user()
    profile, chat = new_id(), new_id()
    moderation.report_targets.authors[profile] = author

    with pytest.raises(ReportTargetNotFoundError):  # не видит или нет такого
        await moderation.report(report(reporter, new_id()))
    with pytest.raises(InvalidReportError) as own:
        await moderation.report(report(author, profile))
    assert own.value.params["reason"] == "own"
    with pytest.raises(InvalidReportError) as reason:  # «не пришёл» — о человеке, не о профиле
        await moderation.report(report(reporter, profile, ReportReason.NO_SHOW))
    assert reason.value.params["field"] == "reason"
    with pytest.raises(InvalidReportError) as context:  # диалог не с этим человеком
        await moderation.report(
            report(reporter, profile, target_type=EntityType.PROFILE, conversation_id=chat)
        )
    assert context.value.params["field"] == "conversation_id"
    assert moderation.report_quota.taken == {}


async def test_report_from_a_chat_keeps_the_conversation_for_the_moderator(
    moderation: Moderation,
) -> None:
    reporter, other = await moderation.user(), await moderation.user()
    chat = new_id()
    moderation.report_targets.authors[other] = other
    moderation.report_targets.conversations[(chat, reporter)] = other

    await moderation.report(
        report(
            reporter,
            other,
            ReportReason.NO_SHOW,
            target_type=EntityType.USER,
            conversation_id=chat,
        )
    )

    [(entity_type, conversation)] = await moderation.rows(
        "SELECT entity_type, evidence -> 0 ->> 'conversation_id' FROM moderation.cases"
        " WHERE entity_id = :id",
        id=other,
    )
    assert (entity_type, conversation) == ("user", str(chat))
