"""Решение — только о версии, которую показала карточка (QA ADV-11): автор поправил объект после
карточки — открытый кейс устарел. Правка через автопроверку или решение, опередившее её,
закрывают его как `superseded` и открывают новый о новой версии — с поводами, жалобами и местом
в очереди прежнего; решение по устаревшему отказывает и ничего не публикует.

Цель — фейк с версиями, кейсы и жалобы — PostgreSQL в откатываемой транзакции.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from app.modules.moderation.application.use_cases.auto_check import AutoCheckCommand
from app.modules.moderation.application.use_cases.create_report import CreateReportCommand
from app.modules.moderation.application.use_cases.decide_case import DecideCaseCommand
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.reports import ReportReason
from app.modules.moderation.errors import CaseSupersededError
from app.platform.ai.port import ContentKind
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import CaseId, UserId, new_id

from .conftest import Moderation

pytestmark = pytest.mark.integration

APPROVED, REJECTED = ModerationDecision.APPROVED, ModerationDecision.REJECTED


async def checked(moderation: Moderation, author: UserId, entity: UUID, *, edit: bool) -> None:
    await moderation.auto_check(
        AutoCheckCommand(
            entity_type=EntityType.PROFILE, entity_id=entity, author_id=author, edit=edit
        )
    )


async def cases(moderation: Moderation, entity: UUID) -> list[tuple[Any, ...]]:
    """Кейсы объекта по порядку открытия: id, статус, причина, версия."""
    return await moderation.rows(
        "SELECT id, status, reason_code, entity_version FROM moderation.cases"
        " WHERE entity_id = :id ORDER BY decided_at NULLS LAST",
        id=entity,
    )


async def new_profile(moderation: Moderation) -> tuple[UserId, UUID, CaseId]:
    """Профиль на первой проверке (всегда человек): кейс P2 о версии 1."""
    author = await moderation.user()
    profile = moderation.profiles.add(
        author, "Электрик, 10 лет опыта", kind=ContentKind.PROFILE, always_review=True
    )
    await checked(moderation, author, profile, edit=False)
    [(case_id, status, _, version)] = await cases(moderation, profile)
    assert (status, version) == ("pending", 1)
    return author, profile, CaseId(case_id)


async def test_edit_after_the_card_supersedes_the_case(moderation: Moderation) -> None:
    author, profile, seen = await new_profile(moderation)
    [opened_at] = await moderation.rows(
        "SELECT created_at, due_at FROM moderation.cases WHERE id = :id", id=seen
    )
    moderation.clock.advance(timedelta(minutes=30))

    moderation.profiles.edit(profile, "Пишите в телеграм @qa_contact_test")
    await checked(moderation, author, profile, edit=True)

    [(old, old_status, reason, _), (new, status, _, version)] = await cases(moderation, profile)
    assert (old, old_status, reason) == (seen, "approved", "superseded")
    assert (status, version) == ("pending", 2)
    # место в очереди прежнее: правками проверку не отодвинуть
    [kept] = await moderation.rows(
        "SELECT created_at, due_at FROM moderation.cases WHERE id = :id", id=new
    )
    assert kept == opened_at
    with pytest.raises(CaseSupersededError):
        await moderation.decide(DecideCaseCommand(case_id=seen, verdict=APPROVED))
    assert moderation.profiles.published == []  # устаревшее одобрение ничего не публикует

    await moderation.decide(DecideCaseCommand(case_id=CaseId(new), verdict=APPROVED))

    assert moderation.profiles.published == [(profile, 2)]  # только версия новой карточки
    [(event,)] = await moderation.rows(
        "SELECT action FROM platform.audit_log WHERE entity_id = :id"
        " AND action = 'moderation.case.superseded'",
        id=seen,
    )
    assert event == "moderation.case.superseded"


async def test_decision_ahead_of_the_edit_check_is_refused_and_reopens_the_case(
    moderation: Moderation,
) -> None:
    """Автопроверка правки ещё в очереди, а модератор уже нажал «Одобрить»: решения нет, кейс
    устарел, новый — о версии, в которой объект сейчас."""
    _, profile, seen = await new_profile(moderation)
    moderation.profiles.edit(profile, "Пишите в телеграм @qa_contact_test")

    with pytest.raises(CaseSupersededError):
        await moderation.decide(
            DecideCaseCommand(case_id=seen, verdict=REJECTED, reason_code="spam_ad")
        )

    assert moderation.profiles.published == []
    assert moderation.profiles.hidden == []
    [(_, old_status, reason, _), (_, status, _, version)] = await cases(moderation, profile)
    assert (old_status, reason, status, version) == ("approved", "superseded", "pending", 2)


async def test_same_version_joins_the_open_case(moderation: Moderation) -> None:
    author, profile, seen = await new_profile(moderation)

    await checked(moderation, author, profile, edit=True)  # повтор проверки той же версии

    [(case_id, status, _, version)] = await cases(moderation, profile)
    assert (case_id, status, version) == (seen, "pending", 1)


async def test_reports_move_to_the_new_case(moderation: Moderation) -> None:
    """Жалоба на объект — кейс без версии; правка его заменяет, жалобу решает новый кейс."""
    reporter, author = await moderation.user(), await moderation.user()
    profile = moderation.profiles.add(
        author, "Электрик", kind=ContentKind.PROFILE, always_review=True
    )
    moderation.report_targets.authors[profile] = author
    filed = await moderation.report(
        CreateReportCommand(
            reporter_id=reporter,
            target_type=EntityType.PROFILE,
            target_id=profile,
            reason=ReportReason.FRAUD,
        )
    )
    moderation.profiles.edit(profile, "Предоплата на карту, пишите @qa")

    await checked(moderation, author, profile, edit=True)

    [(old, _, reason, _), (new, status, _, version)] = await cases(moderation, profile)
    assert (old, reason, status, version) == (filed.report.case_id, "superseded", "pending", 2)
    [(case_id, report_status)] = await moderation.rows(
        "SELECT case_id, status FROM moderation.reports WHERE id = :id", id=filed.report.id
    )
    assert (case_id, report_status) == (new, "open")

    await moderation.decide(
        DecideCaseCommand(case_id=CaseId(new), verdict=REJECTED, reason_code="prepayment_scam")
    )

    [(report_status,)] = await moderation.rows(
        "SELECT status FROM moderation.reports WHERE id = :id", id=filed.report.id
    )
    assert report_status == "resolved"
    assert moderation.profiles.hidden == [(profile, "prepayment_scam")]


async def test_objects_without_versions_are_decided_as_before(moderation: Moderation) -> None:
    """Сообщение, отзыв, фото: версий нет — правок нет, кейс решают как раньше."""
    author = await moderation.user()
    case_id = await moderation.case(author, entity_id=new_id())

    await moderation.decide(DecideCaseCommand(case_id=case_id, verdict=APPROVED))

    [(status, reason)] = await moderation.rows(
        "SELECT status, reason_code FROM moderation.cases WHERE id = :id", id=case_id
    )
    assert (status, reason) == ("approved", None)
