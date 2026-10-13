"""Сигналы риска по итогу автопроверки и их сводка для карточки (domain/risk.py; план
антифрода B2, B6, 2026-10-13): просьба о предоплате — сигнал, повтор у новичка — предлагаемая
тяжесть, кейс о сообщении с предоплатой — об авторе."""

import pytest

from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import (
    PREPAYMENT_SIGNAL,
    Route,
    Routing,
    about_author,
)
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.risk import (
    CONTACT_LEAK_WEIGHT,
    RiskSignal,
    RiskSignalKind,
    RiskSummary,
    content_signals,
    prepayment_requests,
    suggested_severity,
    summarize,
)
from app.modules.moderation.domain.sanctions import Severity
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

AUTHOR = UserId(new_id())
CONTACTS = "detector:contacts:flag:phone, username"
PREPAYMENT, CONTACT_LEAK = RiskSignalKind.PREPAYMENT_REQUEST, RiskSignalKind.CONTACT_LEAK
REREGISTERED = RiskSignalKind.REREGISTERED_AFTER_DELETION


def test_prepayment_signal_for_any_object_and_contacts_only_in_chat() -> None:
    message, job = new_id(), new_id()

    in_chat = content_signals(
        author_id=AUTHOR,
        entity_type=EntityType.MESSAGE,
        entity_id=message,
        signals=(CONTACTS, PREPAYMENT_SIGNAL),
    )
    in_job = content_signals(
        author_id=AUTHOR,
        entity_type=EntityType.JOB,
        entity_id=job,
        signals=(CONTACTS, PREPAYMENT_SIGNAL),
    )
    clean = content_signals(
        author_id=AUTHOR,
        entity_type=EntityType.MESSAGE,
        entity_id=job,
        signals=("rule:spam:flag:x",),
    )

    assert [(s.kind, s.weight, s.ref_type, s.ref_id) for s in in_chat] == [
        (PREPAYMENT, 1.0, "message", message),
        (CONTACT_LEAK, CONTACT_LEAK_WEIGHT, "message", message),
    ]
    assert in_chat[0].dedupe_key == f"prepayment_request:message:{message}"  # один объект — один
    assert [s.kind for s in in_job] == [PREPAYMENT]  # контакты в заявке решает модерация
    assert clean == []


def test_summary_counts_weights_and_sanctions_by_kind() -> None:
    def signal(kind: RiskSignalKind, weight: float = 1.0, **details: object) -> RiskSignal:
        return RiskSignal(user_id=AUTHOR, kind=kind, weight=weight, details=details)

    summaries = summarize(
        [
            signal(PREPAYMENT),
            signal(REREGISTERED, 3.0, had_sanctions=True),
            signal(PREPAYMENT),
            signal(CONTACT_LEAK, CONTACT_LEAK_WEIGHT),
        ]
    )

    assert summaries == (
        RiskSummary(kind=PREPAYMENT, count=2, weight=2.0),
        RiskSummary(kind=REREGISTERED, count=1, weight=3.0, with_sanctions=True),
        RiskSummary(kind=CONTACT_LEAK, count=1, weight=0.5),
    )
    assert prepayment_requests(summaries) == 2
    assert summarize([]) == ()


@pytest.mark.parametrize(
    ("requests", "trust_level", "severity"),
    [
        (2, 0, Severity.SERIOUS),
        (3, 1, Severity.SERIOUS),
        (1, 0, None),  # первая просьба — без предложения
        (2, 2, None),  # уровень 2 — не новичок
        (2, None, None),
    ],
)
def test_repeat_suggests_suspension_only_for_newcomers(
    requests: int, trust_level: int | None, severity: Severity | None
) -> None:
    summaries = (RiskSummary(kind=PREPAYMENT, count=requests, weight=float(requests)),)

    assert suggested_severity(summaries, trust_level=trust_level) is severity


def test_prepayment_message_case_is_about_the_author() -> None:
    review = Routing(route=Route.REVIEW, queue=Queue.FRAUD, signals=(PREPAYMENT_SIGNAL,))
    hidden = Routing(
        route=Route.REVIEW,
        queue=Queue.FRAUD,
        signals=(PREPAYMENT_SIGNAL, "rule:scam:flag:safe deal"),
        flagged=True,
    )
    contacts = Routing(route=Route.REVIEW, queue=Queue.PREMOD, signals=(CONTACTS,))

    assert about_author(EntityType.MESSAGE, review)
    assert not about_author(EntityType.JOB, review)  # заявка — кейс об объекте, как раньше
    assert not about_author(EntityType.MESSAGE, hidden)  # скрытое сообщение вернёт одобрение
    assert not about_author(EntityType.MESSAGE, contacts)
