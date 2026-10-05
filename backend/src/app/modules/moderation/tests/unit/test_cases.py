"""Кейс модерации (DEVELOPMENT_PLAN 2.5a): переходы, поводы, решение и statement of reasons."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.moderation.domain.cases import Case, CaseStatus, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import SanctionStep
from app.modules.moderation.errors import (
    CaseStateError,
    CaseSupersededError,
    CaseTakenError,
    InvalidDecisionError,
)
from app.platform.contracts.events.moderation import (
    AppealDecided,
    CaseOpened,
    ModerationDecision,
    ModerationDecisionMade,
)
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)  # 12:00 в Белграде — рабочее время
AUTHOR, ANA, MARKO = UserId(new_id()), UserId(new_id()), UserId(new_id())
APPROVED, REJECTED = ModerationDecision.APPROVED, ModerationDecision.REJECTED


def opened(
    queue: Queue = Queue.PREMOD,
    trigger: CaseTrigger = CaseTrigger.AUTO_FLAG,
    appeal_of: CaseId | None = None,
) -> Case:
    case = Case.open(
        queue=queue,
        entity_type=EntityType.JOB,
        entity_id=new_id(),
        subject_id=AUTHOR,
        trigger=trigger,
        now=NOW,
        details={"labels": ["contact_leak"]},
        appeal_of=appeal_of,
    )
    case.pull_events()  # CaseOpened — свой тест
    return case


def test_new_case_is_announced_for_the_moderators_chat() -> None:
    case = Case.open(
        queue=Queue.FRAUD,
        entity_type=EntityType.USER,
        entity_id=AUTHOR,
        subject_id=AUTHOR,
        trigger=CaseTrigger.REPORT,
        now=NOW,
    )

    [event] = case.pull_events()
    assert event == CaseOpened(
        case_id=case.id,
        queue="fraud",
        entity_type="user",
        trigger="report",
        occurred_at=NOW,
        event_id=event.event_id,
    )


def test_new_case_waits_in_its_queue_with_a_deadline() -> None:
    case = opened()

    assert case.status is CaseStatus.PENDING
    assert case.is_open
    assert case.due_at == NOW + timedelta(minutes=30)  # P2
    assert case.evidence == [
        {"trigger": "auto_flag", "at": NOW.isoformat(), "labels": ["contact_leak"]}
    ]


def test_second_trigger_moves_the_case_to_the_stricter_queue() -> None:
    first, second = MediaId(new_id()), MediaId(new_id())
    case = opened()
    case.add_trigger(
        queue=Queue.SAFETY,
        trigger=CaseTrigger.REPORT,
        now=NOW + timedelta(minutes=5),
        media_ids=[first, second, first],
    )
    case.add_trigger(queue=Queue.PREMOD, trigger=CaseTrigger.EDIT, now=NOW, media_ids=[second])

    assert case.queue is Queue.SAFETY
    assert case.due_at == NOW + timedelta(minutes=30)  # ближний срок из двух: P2 ещё раньше P0
    assert case.media_ids == (first, second)
    assert [e["trigger"] for e in case.evidence] == ["auto_flag", "report", "edit"]
    assert case.reported


@pytest.mark.parametrize(
    ("queue", "delay_minutes", "due_minutes"),
    [
        (Queue.SAFETY, 5, 35),
        (Queue.FRAUD, 5, 35),
        (Queue.SAFETY, 50, 60),
        (Queue.FRAUD, 110, 120),
    ],
)
def test_premod_trigger_keeps_stricter_queue_and_nearest_deadline(
    queue: Queue, delay_minutes: int, due_minutes: int
) -> None:
    case = opened(queue, CaseTrigger.REPORT)

    case.add_trigger(
        queue=Queue.PREMOD,
        trigger=CaseTrigger.EDIT,
        now=NOW + timedelta(minutes=delay_minutes),
    )

    assert case.queue is queue
    assert case.due_at == NOW + timedelta(minutes=due_minutes)


def status(case: Case) -> CaseStatus:
    return case.status  # без сужения типа mypy между переходами


def test_moderator_takes_escalates_and_admin_decides() -> None:
    case = opened()
    case.take(ANA)
    case.take(ANA)  # повтор ничего не меняет
    with pytest.raises(CaseTakenError):
        case.take(MARKO)

    case.escalate(ANA, note="нужен старший")
    assert status(case) is CaseStatus.ESCALATED
    assert case.assigned_to is None

    case.take(MARKO)
    case.decide(verdict=APPROVED, reason_code=None, policy_version="draft-1", now=NOW, by=MARKO)
    assert status(case) is CaseStatus.APPROVED
    assert case.notes == "нужен старший"


def test_another_moderator_cannot_decide_a_taken_case() -> None:
    case = opened()
    case.take(ANA)

    with pytest.raises(CaseTakenError):
        case.decide(verdict=REJECTED, reason_code="spam_ad", policy_version="v", now=NOW, by=MARKO)
    with pytest.raises(CaseTakenError):
        case.escalate(MARKO)


def test_automated_decision_only_while_nobody_reviews() -> None:
    case = opened()
    case.take(ANA)

    with pytest.raises(CaseStateError):
        case.decide(verdict=APPROVED, reason_code=None, policy_version="v", now=NOW, by=None)


@pytest.mark.parametrize(
    ("verdict", "reason", "sanction", "field"),
    [
        (REJECTED, None, None, "reason_code"),  # отказ — только с причиной
        (REJECTED, "Contact Leak", None, "reason_code"),  # код машинный
        (REJECTED, "x" * 65, None, "reason_code"),
        (APPROVED, None, SanctionStep.WARNING, "sanction"),  # санкция — только при отказе
    ],
)
def test_incomplete_decision_is_refused(
    verdict: ModerationDecision, reason: str | None, sanction: SanctionStep | None, field: str
) -> None:
    case = opened()

    with pytest.raises(InvalidDecisionError) as raised:
        case.decide(
            verdict=verdict,
            reason_code=reason,
            policy_version="v",
            now=NOW,
            by=ANA,
            sanction=sanction,
        )
    assert raised.value.params == {"field": field}
    assert case.status is CaseStatus.PENDING


def test_rejection_is_a_statement_of_reasons() -> None:
    case = opened()

    case.decide(
        verdict=REJECTED,
        reason_code="contact_leak",
        policy_version="draft-1",
        now=NOW,
        by=None,
        sanction=SanctionStep.WARNING,
    )

    assert case.status is CaseStatus.REJECTED
    assert (case.decided_by, case.reason_code, case.policy_version, case.decided_at) == (
        None,
        "contact_leak",
        "draft-1",
        NOW,
    )
    [event] = case.pull_events()
    assert event == ModerationDecisionMade(
        case_id=case.id,
        author_id=AUTHOR,
        entity_type="job",
        entity_id=case.entity_id,
        decision=REJECTED,
        decision_code="contact_leak",
        automated=True,
        sanction="warning",
        occurred_at=NOW,
        event_id=event.event_id,
    )


def test_decided_case_is_closed() -> None:
    case = opened()
    case.decide(verdict=APPROVED, reason_code=None, policy_version="v", now=NOW, by=ANA)

    actions: list[Callable[[], None]] = [
        lambda: case.take(ANA),
        lambda: case.escalate(ANA),
        lambda: case.add_trigger(queue=Queue.FRAUD, trigger=CaseTrigger.REPORT, now=NOW),
        lambda: case.decide(verdict=REJECTED, reason_code="x", policy_version="v", now=NOW, by=ANA),
    ]
    for action in actions:
        with pytest.raises(CaseStateError):
            action()


def test_appeal_outcome_is_not_a_new_rejection_notice() -> None:
    decision = CaseId(new_id())
    case = opened(Queue.APPEALS, CaseTrigger.APPEAL, appeal_of=decision)

    case.decide(verdict=REJECTED, reason_code="spam_ad", policy_version="v", now=NOW, by=ANA)

    [event] = case.pull_events()  # итог апелляции, а не новый отказ
    assert event == AppealDecided(
        case_id=case.id,
        appeal_of=decision,
        user_id=AUTHOR,
        granted=False,
        decision_code="spam_ad",
        occurred_at=NOW,
        event_id=event.event_id,
    )
    assert case.due_at == NOW + timedelta(hours=72)


def test_granted_appeal_is_announced() -> None:
    case = opened(Queue.APPEALS, CaseTrigger.APPEAL, appeal_of=CaseId(new_id()))

    case.decide(verdict=APPROVED, reason_code=None, policy_version="v", now=NOW, by=ANA)

    [event] = case.pull_events()
    assert isinstance(event, AppealDecided)
    assert event.granted


def test_edit_after_the_card_supersedes_the_case_keeping_its_place_in_the_queue() -> None:
    """ADV-11: карточка показывает версию 1, автор поправил объект — кейс устарел: закрыт без
    решения и санкции, новый — о версии 2, с поводами прежнего, его временем и сроком."""
    case = Case.open(
        queue=Queue.PREMOD,
        entity_type=EntityType.JOB,
        entity_id=new_id(),
        subject_id=AUTHOR,
        trigger=CaseTrigger.NEW_CONTENT,
        now=NOW,
        details={"signals": ["detector:contacts:flag:phone"]},
        entity_version=1,
    )
    case.pull_events()
    later = NOW + timedelta(hours=1)

    assert not case.is_stale(1)
    assert not case.is_stale(None)  # у объекта нет версий — сравнивать не с чем
    assert case.is_stale(2)
    successor = case.supersede(
        queue=Queue.PREMOD,
        trigger=CaseTrigger.EDIT,
        now=later,
        details={"signals": ["detector:contacts:flag:username"]},
        entity_version=2,
    )

    assert (case.status, case.reason_code, case.decided_at) == (
        CaseStatus.APPROVED,
        "superseded",
        later,
    )
    assert case.is_superseded
    assert case.pull_events() == []  # ни statement of reasons, ни санкции
    assert (successor.status, successor.entity_version) == (CaseStatus.PENDING, 2)
    assert (successor.opened_at, successor.due_at) == (case.opened_at, case.due_at)
    assert [entry["trigger"] for entry in successor.evidence] == ["new_content", "edit"]
    assert successor.supersedes == case.id
    [event] = successor.pull_events()
    assert event == CaseOpened(
        case_id=successor.id,
        queue="premod",
        entity_type="job",
        trigger="edit",
        occurred_at=later,
        event_id=event.event_id,
    )


@pytest.mark.parametrize(
    "act",
    [
        lambda case: case.decide(
            verdict=APPROVED, reason_code=None, policy_version="1", now=NOW, by=ANA
        ),
        lambda case: case.take(ANA),
        lambda case: case.escalate(ANA),
    ],
    ids=["decide", "take", "escalate"],
)
def test_superseded_case_refuses_any_decision(act: Callable[[Case], None]) -> None:
    case = opened()
    case.supersede(queue=Queue.PREMOD, trigger=CaseTrigger.EDIT, now=NOW, entity_version=2)

    with pytest.raises(CaseSupersededError):
        act(case)
    assert case.reason_code == "superseded"


def test_escalated_case_stays_with_the_senior_after_an_edit() -> None:
    case = opened()
    case.escalate(ANA, note="мошенничество?")

    successor = case.supersede(
        queue=Queue.FRAUD, trigger=CaseTrigger.EDIT, now=NOW, entity_version=2
    )

    assert (successor.status, successor.queue, successor.notes) == (
        CaseStatus.ESCALATED,
        Queue.FRAUD,
        "мошенничество?",
    )
