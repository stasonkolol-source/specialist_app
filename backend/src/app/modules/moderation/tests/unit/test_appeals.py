"""Апелляция и карточка кейса (DEVELOPMENT_PLAN 2.5b): что можно обжаловать, кнопки карточки в
чате модераторов (текст карточки — test_case_card.py)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.moderation.application.case_card import (
    CONTENT_REASONS,
    DISPUTE_REASONS,
    card_buttons,
    reason_buttons,
    severity_buttons,
)
from app.modules.moderation.domain.appeals import APPEAL_WINDOW, check_appealable
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.errors import AppealTargetNotFoundError, AppealWindowClosedError
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id
from app.platform.telegram.callbacks import MAX_CALLBACK_DATA, CallbackAction, parse_callback
from app.platform.telegram.port import CallbackButton

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
AUTHOR, ANA = UserId(new_id()), UserId(new_id())


def decided(verdict: ModerationDecision = ModerationDecision.REJECTED) -> Case:
    case = Case.open(
        queue=Queue.FRAUD,
        entity_type=EntityType.JOB,
        entity_id=new_id(),
        subject_id=AUTHOR,
        trigger=CaseTrigger.REPORT,
        now=NOW,
        details={"signals": ["report:fraud"]},
    )
    reason = "prepayment_scam" if verdict is ModerationDecision.REJECTED else None
    case.decide(verdict=verdict, reason_code=reason, policy_version="v", now=NOW, by=ANA)
    return case


def test_own_rejection_can_be_appealed_for_six_months() -> None:
    check_appealable(decided(), AUTHOR, NOW + APPEAL_WINDOW)

    with pytest.raises(AppealWindowClosedError):
        check_appealable(decided(), AUTHOR, NOW + APPEAL_WINDOW + timedelta(minutes=1))


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(decided(ModerationDecision.APPROVED), id="no violation"),
        pytest.param(
            Case.open(
                queue=Queue.FRAUD,
                entity_type=EntityType.JOB,
                entity_id=new_id(),
                subject_id=AUTHOR,
                trigger=CaseTrigger.REPORT,
                now=NOW,
            ),
            id="not decided",
        ),
    ],
)
def test_nothing_to_appeal(case: Case) -> None:
    with pytest.raises(AppealTargetNotFoundError):
        check_appealable(case, AUTHOR, NOW)


def test_only_the_subject_appeals() -> None:
    with pytest.raises(AppealTargetNotFoundError):
        check_appealable(decided(), ANA, NOW)


def test_appeal_is_not_appealed() -> None:
    appeal = Case.open(
        queue=Queue.APPEALS,
        entity_type=EntityType.JOB,
        entity_id=new_id(),
        subject_id=AUTHOR,
        trigger=CaseTrigger.APPEAL,
        now=NOW,
        appeal_of=CaseId(new_id()),
    )
    appeal.decide(
        verdict=ModerationDecision.REJECTED,
        reason_code="decision_upheld",
        policy_version="v",
        now=NOW,
        by=ANA,
    )
    with pytest.raises(AppealTargetNotFoundError):
        check_appealable(appeal, AUTHOR, NOW)


@pytest.fixture(scope="module")
def translator() -> Translator:
    return Translator.load()


def dispute() -> Case:
    return Case.open(
        queue=Queue.FRAUD,
        entity_type=EntityType.DISPUTE,
        entity_id=new_id(),
        subject_id=AUTHOR,
        trigger=CaseTrigger.DISPUTE,
        now=NOW,
        details={"signals": ["dispute:no_show"]},
        media_ids=[MediaId(new_id()), MediaId(new_id())],
    )


def labels(lines: tuple[object, ...]) -> list[str]:
    flat = [b for line in lines for b in (line if isinstance(line, tuple) else (line,))]
    assert all(isinstance(b, CallbackButton) for b in flat)
    return [b.text for b in flat if isinstance(b, CallbackButton)]


def test_dispute_buttons_are_outcomes(translator: Translator) -> None:
    case = dispute()

    assert labels(card_buttons(case, translator)) == [
        "Выполнено",
        "Отменить с причиной",
        "Эскалировать",
    ]
    assert labels(reason_buttons(case, translator)) == [*DISPUTE_REASONS, "« Назад"]


def test_content_buttons_and_reason_picker_fit_callback_data(translator: Translator) -> None:
    case = decided()  # статус не важен: важны кнопки

    assert labels(card_buttons(case, translator)) == [
        "Одобрить",
        "Отклонить с причиной",
        "Эскалировать",
    ]
    rows = (
        *reason_buttons(case, translator),
        *severity_buttons(case.id, "not_a_service_request", translator),
    )
    flat = [b for line in rows for b in (line if isinstance(line, tuple) else (line,))]
    for button in flat:
        assert isinstance(button, CallbackButton)
        assert len(button.data.encode()) <= MAX_CALLBACK_DATA
        assert parse_callback(button.data) is not None
    assert {b.text for b in flat} >= set(CONTENT_REASONS)
    sanction = [
        b
        for b in flat
        if isinstance(b, CallbackButton) and b.data.startswith(CallbackAction.CASE_SANCTION)
    ]
    assert [parse_callback(b.data).arg for b in sanction] == [  # type: ignore[union-attr]
        f"{code}not_a_service_request" for code in "nmsc"
    ]
