"""Кейсы, лестница санкций, сигналы риска, SLA и legal hold (DEVELOPMENT_PLAN 2.5a).

Use cases на PostgreSQL в откатываемой транзакции. Фасад identity — фейк (ADR-0020 §11):
санкцию он записывает строкой identity.restrictions, как настоящий; сквозной путь через
настоящий фасад — tests/integration/test_moderation_sanctions.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.identity.api import Action, RestrictionIn, TelegramUserView, UserSummary
from app.modules.moderation.application.queries import ModerationQueries
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
    RecordRateLimitSignalsCommand,
)
from app.modules.moderation.application.use_cases.take_case import (
    EscalateCase,
    EscalateCaseCommand,
    TakeCase,
    TakeCaseCommand,
)
from app.modules.moderation.domain.cases import Case, CaseStatus, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import SanctionStep, Severity
from app.modules.moderation.errors import CaseAlreadyOpenError, CaseTakenError
from app.modules.moderation.infrastructure.cases import (
    SqlCaseRepository,
    SqlRiskSignals,
    SqlSanctionRepository,
)
from app.modules.moderation.infrastructure.legal_hold import CasesLegalHold
from app.modules.moderation.infrastructure.queries import SqlCaseStats
from app.platform.audit.sql import SqlAuditLog
from app.platform.contracts.events.moderation import ModerationDecision, ModerationDecisionMade
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.ids import CaseId, MediaId, RestrictionId, UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.clock import FakeClock
from app.platform.testing.queue import queued_tasks

pytestmark = pytest.mark.integration

REJECTED, APPROVED = ModerationDecision.REJECTED, ModerationDecision.APPROVED
ON_DECISION = TaskRef("test.on_decision", ModerationDecisionMade)
START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)  # 10:00 в Белграде


@dataclass
class FakeIdentity:
    """IdentityApi: санкция — строка identity.restrictions (FK из moderation.sanctions)."""

    session: AsyncSession
    known: set[UserId] = field(default_factory=set)
    restricted: list[RestrictionIn] = field(default_factory=list)
    violations: list[UserId] = field(default_factory=list)

    async def get_user(self, user_id: UserId) -> UserSummary | None:
        if user_id not in self.known:
            return None
        return UserSummary(
            id=user_id,
            display_name="Ana",
            ui_locale=Locale.SR_LATN,
            trust_level=0,
            phone_verified=False,
            is_deleted=False,
            created_at=START,
        )

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return None

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return None

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        return None

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        self.restricted.append(data)
        restriction_id = RestrictionId(new_id())
        await self.session.execute(
            text(
                "INSERT INTO identity.restrictions"
                " (id, user_id, kind, reason_code, source, case_id, ends_at)"
                " VALUES (:id, :user_id, :kind, :reason, 'moderation', :case_id, :ends_at)"
            ),
            {
                "id": restriction_id,
                "user_id": data.user_id,
                "kind": data.kind.value,
                "reason": data.reason_code,
                "case_id": data.case_id,
                "ends_at": data.ends_at,
            },
        )
        return restriction_id

    async def record_violation(self, user_id: UserId) -> None:
        self.violations.append(user_id)


@dataclass
class FakePolicy:
    current: str = "draft-1"

    async def version(self) -> str:
        return self.current


@dataclass
class FakeOverflows:
    days: dict[date, dict[UserId, Mapping[str, int]]] = field(default_factory=dict)

    async def by_user(self, day: date) -> Mapping[UserId, Mapping[str, int]]:
        return self.days.get(day, {})


@dataclass
class Moderation:
    session: AsyncSession
    clock: FakeClock
    uow: SqlAlchemyUnitOfWork
    identity: FakeIdentity
    overflows: FakeOverflows
    open: OpenCase
    take: TakeCase
    escalate: EscalateCase
    decide: DecideCase
    rate_limit_signals: RecordRateLimitSignals
    queries: ModerationQueries
    hold: CasesLegalHold
    cases: SqlCaseRepository

    async def user(self) -> UserId:
        user_id = await insert_user(self.session)
        self.identity.known.add(user_id)
        return user_id

    async def case(
        self,
        subject: UserId,
        *,
        queue: Queue = Queue.PREMOD,
        trigger: CaseTrigger = CaseTrigger.AUTO_FLAG,
        entity_type: EntityType = EntityType.JOB,
        entity_id: UUID | None = None,
        media: tuple[MediaId, ...] = (),
    ) -> CaseId:
        return await self.open(
            OpenCaseCommand(
                queue=queue,
                entity_type=entity_type,
                entity_id=entity_id or new_id(),
                subject_id=subject,
                trigger=trigger,
                details={"labels": ["contact_leak"]},
                media_ids=media,
            )
        )

    async def rows(self, sql: str, **params: object) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in (await self.session.execute(text(sql), params)).all()]


@pytest.fixture
def moderation(db_session: AsyncSession, procrastinate_app: procrastinate.App) -> Moderation:
    events = EventRegistry()
    events.subscribe(ModerationDecisionMade, ON_DECISION)
    clock = FakeClock(START)
    uow = make_uow(db_session, procrastinate_app, events)
    cases = SqlCaseRepository(db_session, uow)
    signals = SqlRiskSignals(db_session, uow)
    audit = SqlAuditLog(db_session, uow)
    identity = FakeIdentity(db_session)
    overflows = FakeOverflows()
    return Moderation(
        session=db_session,
        clock=clock,
        uow=uow,
        identity=identity,
        overflows=overflows,
        open=OpenCase(uow, cases, audit, clock),
        take=TakeCase(uow, cases, audit),
        escalate=EscalateCase(uow, cases, audit),
        decide=DecideCase(
            uow,
            cases,
            SqlSanctionRepository(db_session, uow),
            signals,
            identity,
            FakePolicy(),
            audit,
            clock,
        ),
        rate_limit_signals=RecordRateLimitSignals(uow, overflows, signals, identity, clock),
        queries=ModerationQueries(SqlCaseStats(db_session), clock),
        hold=CasesLegalHold(db_session),
        cases=cases,
    )


def reject(
    case_id: CaseId, severity: Severity | None = Severity.MINOR, reason: str = "contact_leak"
) -> DecideCaseCommand:
    return DecideCaseCommand(
        case_id=case_id, verdict=REJECTED, reason_code=reason, severity=severity
    )


async def test_second_trigger_goes_into_the_open_case(moderation: Moderation) -> None:
    author = await moderation.user()
    job = new_id()

    first = await moderation.case(author, entity_id=job)
    second = await moderation.case(
        author, entity_id=job, queue=Queue.SAFETY, trigger=CaseTrigger.REPORT
    )

    assert second == first
    [(queue, triggers)] = await moderation.rows(
        "SELECT queue, jsonb_array_length(evidence) FROM moderation.cases WHERE entity_id = :id",
        id=job,
    )
    assert (queue, triggers) == ("safety", 2)
    assert await moderation.rows(
        "SELECT action, actor_kind FROM platform.audit_log WHERE entity_id = :id", id=first
    ) == [("moderation.case.opened", "system")]


async def test_one_open_case_per_object_is_enforced_by_the_database(
    moderation: Moderation,
) -> None:
    author = await moderation.user()
    job = new_id()
    await moderation.case(author, entity_id=job)
    twin = Case.open(
        queue=Queue.FRAUD,
        entity_type=EntityType.JOB,
        entity_id=job,
        subject_id=author,
        trigger=CaseTrigger.REPORT,
        now=moderation.clock.now(),
    )

    with pytest.raises(CaseAlreadyOpenError):  # параллельный повод: команда повторится
        async with moderation.uow:
            await moderation.cases.add(twin)


async def test_minor_violations_climb_the_ladder(moderation: Moderation) -> None:
    author, moderator = await moderation.user(), await moderation.user()
    decisions = []
    for _ in range(4):
        case_id = await moderation.case(author)
        await moderation.take(TakeCaseCommand(case_id=case_id, moderator_id=moderator))
        decisions.append(
            await moderation.decide(
                DecideCaseCommand(
                    case_id=case_id,
                    verdict=REJECTED,
                    reason_code="contact_leak",
                    severity=Severity.MINOR,
                    moderator_id=moderator,
                )
            )
        )

    assert [d.sanction for d in decisions] == [
        SanctionStep.WARNING,
        SanctionStep.STRIKE_1,
        SanctionStep.STRIKE_2,
        SanctionStep.BAN,
    ]
    assert decisions[0].restriction_id is None  # предупреждение ничего не запрещает
    assert moderation.identity.violations == [author]
    now = moderation.clock.now()
    assert [(r.kind.value, r.ends_at, r.reason_code) for r in moderation.identity.restricted] == [
        ("limited", now + timedelta(days=7), "contact_leak"),
        ("responding_blocked", now + timedelta(days=30), "contact_leak"),
        ("banned", None, "contact_leak"),
    ]
    assert {r.created_by for r in moderation.identity.restricted} == {moderator}
    steps = await moderation.rows(
        "SELECT step, expires_at IS NOT NULL, restriction_id IS NOT NULL"
        " FROM moderation.sanctions WHERE user_id = :id ORDER BY created_at, step",
        id=author,
    )
    assert sorted(steps) == [
        ("ban", False, True),
        ("strike_1", True, True),
        ("strike_2", True, True),
        ("warning", True, False),
    ]
    decided = await queued_tasks(moderation.session, ON_DECISION.name)
    assert [(t.payload["sanction"], t.payload["automated"]) for t in decided] == [
        ("warning", False),
        ("strike_1", False),
        ("strike_2", False),
        ("ban", False),
    ]
    actions = await moderation.rows(
        "SELECT action FROM platform.audit_log WHERE actor_id = :id ORDER BY id", id=moderator
    )
    assert [a for (a,) in actions].count("moderation.sanction.imposed") == 4


async def test_warnings_and_strikes_burn_out_after_180_days(moderation: Moderation) -> None:
    author = await moderation.user()
    first = await moderation.decide(reject(await moderation.case(author)))

    moderation.clock.advance(timedelta(days=181))
    later = await moderation.decide(reject(await moderation.case(author)))

    assert (first.sanction, later.sanction) == (SanctionStep.WARNING, SanctionStep.WARNING)


async def test_serious_violation_suspends_and_decision_without_severity_does_not(
    moderation: Moderation,
) -> None:
    author = await moderation.user()

    hidden = await moderation.decide(reject(await moderation.case(author), severity=None))
    suspended = await moderation.decide(
        reject(await moderation.case(author), severity=Severity.SERIOUS, reason="prepayment_scam")
    )

    assert (hidden.status, hidden.sanction) == (CaseStatus.REJECTED, None)
    assert suspended.sanction is SanctionStep.SUSPENSION
    [restriction] = moderation.identity.restricted
    assert (restriction.kind.value, restriction.ends_at) == ("suspended", None)
    [automated] = [
        t.payload
        for t in await queued_tasks(moderation.session, ON_DECISION.name)
        if t.payload["case_id"] == str(hidden.case_id)
    ]
    assert automated["automated"] is True  # без модератора — автоматическое решение


async def test_confirmed_report_is_a_risk_signal(moderation: Moderation) -> None:
    author = await moderation.user()
    reported = await moderation.case(author, queue=Queue.FRAUD, trigger=CaseTrigger.REPORT)
    cleared = await moderation.case(author, queue=Queue.FRAUD, trigger=CaseTrigger.REPORT)

    await moderation.decide(reject(reported, severity=None, reason="prepayment_scam"))
    await moderation.decide(DecideCaseCommand(case_id=cleared, verdict=APPROVED))

    assert await moderation.rows(
        "SELECT signal, ref_type, ref_id FROM moderation.risk_signals WHERE user_id = :id",
        id=author,
    ) == [("report_confirmed", "moderation.case", reported)]
    assert moderation.identity.violations == [author]  # жалоба подтверждена — нарушение


async def test_taken_case_belongs_to_its_moderator(moderation: Moderation) -> None:
    author, ana, marko = await moderation.user(), await moderation.user(), await moderation.user()
    case_id = await moderation.case(author)
    await moderation.take(TakeCaseCommand(case_id=case_id, moderator_id=ana))

    with pytest.raises(CaseTakenError):
        await moderation.take(TakeCaseCommand(case_id=case_id, moderator_id=marko))
    await moderation.escalate(EscalateCaseCommand(case_id=case_id, moderator_id=ana, note="P0?"))
    await moderation.take(TakeCaseCommand(case_id=case_id, moderator_id=marko))

    [(status, assigned, notes)] = await moderation.rows(
        "SELECT status, assigned_to, notes FROM moderation.cases WHERE id = :id", id=case_id
    )
    assert (status, assigned, notes) == ("in_review", marko, "P0?")
    assert await moderation.rows(
        "SELECT action, actor_id FROM platform.audit_log WHERE entity_id = :id ORDER BY id",
        id=case_id,
    ) == [
        ("moderation.case.opened", None),
        ("moderation.case.taken", ana),
        ("moderation.case.escalated", ana),
        ("moderation.case.taken", marko),
    ]


async def test_sla_report_counts_decisions_in_time_and_overdue(moderation: Moderation) -> None:
    author = await moderation.user()
    since = moderation.clock.now()
    in_time = await moderation.case(author, queue=Queue.SAFETY)
    late = await moderation.case(author, queue=Queue.PREMOD)
    await moderation.case(author, queue=Queue.PREMOD)  # останется открытым
    await moderation.decide(DecideCaseCommand(case_id=in_time, verdict=APPROVED))
    moderation.clock.advance(timedelta(minutes=45))  # P2 — 30 минут
    await moderation.decide(DecideCaseCommand(case_id=late, verdict=APPROVED))
    moderation.clock.advance(timedelta(minutes=1))  # период — [since, сейчас)

    sla = {row.queue: row for row in await moderation.queries.sla(since=since)}

    assert (sla[Queue.SAFETY].decided, sla[Queue.SAFETY].decided_in_time) == (1, 1)
    premod = sla[Queue.PREMOD]
    assert (premod.decided, premod.decided_in_time, premod.open, premod.overdue) == (1, 0, 1, 1)
    assert premod.in_time_share == 0.0
    assert sla[Queue.APPEALS].in_time_share is None


async def test_open_cases_hold_their_evidence(moderation: Moderation) -> None:
    author = await moderation.user()
    evidence, reported, closed, free = (MediaId(new_id()) for _ in range(4))
    await moderation.case(author, media=(evidence,))
    await moderation.case(author, entity_type=EntityType.MEDIA, entity_id=reported)
    done = await moderation.case(author, media=(closed,))
    await moderation.decide(DecideCaseCommand(case_id=done, verdict=APPROVED))

    async with moderation.uow:
        held = await moderation.hold.held([evidence, reported, closed, free])

    assert held == {evidence, reported}


async def test_systematic_429_become_risk_signals_once(moderation: Moderation) -> None:
    author, stranger = await moderation.user(), UserId(new_id())
    today = moderation.clock.now().date()
    moderation.overflows.days[today] = {
        author: {"media.uploads": 7, "auth.telegram_user": 2},
        stranger: {"media.uploads": 50},  # не пользователь площадки — пропускаем
    }
    moderation.overflows.days[today - timedelta(days=1)] = {author: {"media.uploads": 5}}

    first = await moderation.rate_limit_signals(RecordRateLimitSignalsCommand())
    again = await moderation.rate_limit_signals(RecordRateLimitSignalsCommand())

    assert (first, again) == (2, 0)
    rows = await moderation.rows(
        "SELECT details->>'day', details->>'count' FROM moderation.risk_signals"
        " WHERE user_id = :id AND signal = 'rate_limit_exceeded' ORDER BY 1",
        id=author,
    )
    assert rows == [
        ((today - timedelta(days=1)).isoformat(), "5"),
        (today.isoformat(), "7"),
    ]
