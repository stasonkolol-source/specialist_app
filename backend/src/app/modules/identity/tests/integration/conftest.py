"""Фикстуры identity: репозитории и use cases на сессии теста (откат в конце).

Внешнее — фейки (ADR-0020 §11): denylist Valkey, версии документов из client-config,
фасад geo. JWT подписывается настоящим ключом: это чистый код без I/O.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import procrastinate
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.identity.application.access import AccessChecker
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.facade import IdentityFacade
from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.application.use_cases.accept_consents import AcceptConsents
from app.modules.identity.application.use_cases.age_trust_levels import AgeTrustLevels
from app.modules.identity.application.use_cases.authenticate_telegram import AuthenticateTelegram
from app.modules.identity.application.use_cases.grant_staff_role import GrantStaffRole
from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.application.use_cases.refresh_session import RefreshSession
from app.modules.identity.application.use_cases.revoke_restricted_sessions import (
    RevokeRestrictedSessions,
)
from app.modules.identity.application.use_cases.update_profile import UpdateProfile
from app.modules.identity.domain.restriction import RestrictionKind, RestrictionSource
from app.modules.identity.infrastructure.models import RestrictionRow, UserRoleRow
from app.modules.identity.infrastructure.queries import SqlIdentityQuery
from app.modules.identity.infrastructure.repositories import (
    SqlConsentRepository,
    SqlRestrictionRepository,
    SqlRoleRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from app.modules.identity.tests.fakes import FakeGeo
from app.platform.audit.sql import SqlAuditLog
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Role
from app.platform.queue.dispatcher import EventRegistry
from app.platform.security.jwt import AccessTokens, JwtKeys, SigningKey
from app.platform.testing.clock import FakeClock
from app.platform.testing.config import FakeLegalVersions

CONFIG = IdentityConfig(
    bot_id=7000000001, refresh_ttl_tma=timedelta(days=7), refresh_ttl_mobile=timedelta(days=30)
)
KEY = SigningKey.generate("test")


@dataclass
class FakeRevocations:
    revoked: list[str] = field(default_factory=list)

    async def revoke(self, session_id: str) -> None:
        self.revoked.append(session_id)


@dataclass
class Identity:
    """Модуль identity, собранный на сессии теста."""

    session: AsyncSession
    clock: FakeClock
    uow: SqlAlchemyUnitOfWork
    users: SqlUserRepository
    sessions: SqlSessionRepository
    query: SqlIdentityQuery
    tokens: AccessTokens
    revocations: FakeRevocations
    legal: FakeLegalVersions
    geo: FakeGeo
    access: AccessChecker
    authenticate: AuthenticateTelegram
    refresh: RefreshSession
    logout: Logout
    update_profile: UpdateProfile
    accept_consents: AcceptConsents
    facade: IdentityFacade
    age_trust_levels: AgeTrustLevels
    revoke_restricted_sessions: RevokeRestrictedSessions
    grant_staff_role: GrantStaffRole

    async def restrict(
        self, user_id: UserId, kind: RestrictionKind, *, ends_at: datetime | None = None
    ) -> None:
        self.session.add(
            RestrictionRow(
                id=new_id(),
                user_id=user_id,
                kind=kind,
                reason_code="test",
                source=RestrictionSource.MODERATION,
                starts_at=self.clock.now() - timedelta(minutes=1),
                ends_at=ends_at,
            )
        )
        await self.session.commit()

    async def grant(self, user_id: UserId, role: Role) -> None:
        self.session.add(UserRoleRow(user_id=user_id, role=role))
        await self.session.commit()


@pytest.fixture
def events() -> EventRegistry:
    """Подписки теста: событие попадает в procrastinate_jobs, только если на него подписаны."""
    return EventRegistry()


@pytest.fixture
def identity(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, events: EventRegistry
) -> Identity:
    clock = FakeClock()
    uow = make_uow(db_session, procrastinate_app, events)
    users = SqlUserRepository(db_session, uow)
    sessions = SqlSessionRepository(db_session, uow)
    query = SqlIdentityQuery(db_session)
    tokens = AccessTokens(JwtKeys.of(KEY), clock, issuer="sosed", ttl=timedelta(minutes=15))
    revocations = FakeRevocations()
    legal = FakeLegalVersions()
    geo = FakeGeo()
    access = AccessChecker(query, legal, clock)
    trust = TrustRecalculation(query)
    audit = SqlAuditLog(db_session, uow)
    return Identity(
        session=db_session,
        clock=clock,
        uow=uow,
        users=users,
        sessions=sessions,
        query=query,
        tokens=tokens,
        revocations=revocations,
        legal=legal,
        geo=geo,
        access=access,
        authenticate=AuthenticateTelegram(uow, users, sessions, query, tokens, CONFIG, clock),
        refresh=RefreshSession(
            uow,
            users,
            sessions,
            query,
            tokens,
            revocations,
            audit,
            CONFIG,
            clock,
        ),
        logout=Logout(uow, sessions, revocations, clock),
        update_profile=UpdateProfile(uow, users, geo, clock),
        accept_consents=AcceptConsents(
            uow, users, SqlConsentRepository(db_session, uow), legal, clock
        ),
        facade=IdentityFacade(
            uow, query, users, SqlRestrictionRepository(db_session, uow), access, trust, clock
        ),
        age_trust_levels=AgeTrustLevels(uow, users, trust, clock),
        revoke_restricted_sessions=RevokeRestrictedSessions(uow, sessions, revocations, clock),
        grant_staff_role=GrantStaffRole(uow, users, SqlRoleRepository(db_session, uow), audit),
    )


def telegram_profile(**overrides: object) -> TelegramProfile:
    values: dict[str, object] = {
        "id": 279058397 + new_id().int % 1_000_000,
        "first_name": "Ana",
        "last_name": "Petrović",
        "username": "ana_ns",
        "language_code": "sr",
        "is_premium": True,
        "allows_write_to_pm": True,
    }
    return TelegramProfile(**(values | overrides))  # type: ignore[arg-type]
