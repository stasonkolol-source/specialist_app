"""Фикстуры moderation: use cases на сессии теста (откат в конце), фасады — фейки."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.queries import ModerationQueries
from app.modules.moderation.application.use_cases.auto_check import AutoCheck
from app.modules.moderation.application.use_cases.decide_case import DecideCase
from app.modules.moderation.application.use_cases.open_case import (
    CaseOpener,
    OpenCase,
    OpenCaseCommand,
)
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
)
from app.modules.moderation.application.use_cases.take_case import EscalateCase, TakeCase
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.infrastructure.cases import (
    SqlCaseRepository,
    SqlRiskSignals,
    SqlSanctionRepository,
)
from app.modules.moderation.infrastructure.legal_hold import CasesLegalHold
from app.modules.moderation.infrastructure.queries import SqlCaseQueue, SqlCaseStats
from app.modules.moderation.tests.fakes import (
    START,
    FakeClassifier,
    FakeFlags,
    FakeIdentity,
    FakeMetrics,
    FakeModeration,
    FakeOverflows,
    FakePolicy,
    FakeRuleSource,
    FakeTarget,
    FakeTargets,
    NoVelocity,
)
from app.platform.audit.sql import SqlAuditLog
from app.platform.contracts.events.moderation import ModerationDecisionMade
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.clock import FakeClock

ON_DECISION = TaskRef("test.on_decision", ModerationDecisionMade)


@dataclass
class Moderation:
    """Модуль moderation, собранный на сессии теста."""

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
    auto_check: AutoCheck
    rules: FakeRuleSource
    omni: FakeModeration
    classifier: FakeClassifier
    flags: FakeFlags
    metrics: FakeMetrics
    jobs: FakeTarget = field(default_factory=FakeTarget)
    profiles: FakeTarget = field(default_factory=FakeTarget)

    async def user(self, *, trust_level: int = 0) -> UserId:
        user_id = await insert_user(self.session)
        self.identity.known.add(user_id)
        self.identity.trust[user_id] = trust_level
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
    opener = CaseOpener(cases, audit, clock)
    jobs, profiles = FakeTarget(), FakeTarget()
    targets = FakeTargets({EntityType.JOB: jobs, EntityType.PROFILE: profiles})
    rules, omni, classifier = FakeRuleSource(), FakeModeration(), FakeClassifier()
    flags, metrics = FakeFlags(), FakeMetrics()
    return Moderation(
        session=db_session,
        clock=clock,
        uow=uow,
        identity=identity,
        overflows=overflows,
        open=OpenCase(uow, opener),
        take=TakeCase(uow, cases, audit),
        escalate=EscalateCase(uow, cases, audit),
        decide=DecideCase(
            uow,
            cases,
            SqlSanctionRepository(db_session, uow),
            signals,
            identity,
            targets,
            FakePolicy(),
            audit,
            clock,
        ),
        rate_limit_signals=RecordRateLimitSignals(uow, overflows, signals, identity, clock),
        queries=ModerationQueries(SqlCaseStats(db_session), SqlCaseQueue(db_session), clock),
        hold=CasesLegalHold(db_session),
        cases=cases,
        auto_check=AutoCheck(
            uow,
            targets,
            ContentRulesChecker(rules, NoVelocity()),
            omni,
            classifier,
            opener,
            identity,
            flags,
            metrics,
            audit,
        ),
        rules=rules,
        omni=omni,
        classifier=classifier,
        flags=flags,
        metrics=metrics,
        jobs=jobs,
        profiles=profiles,
    )
