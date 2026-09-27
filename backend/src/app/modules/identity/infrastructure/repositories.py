"""Репозитории агрегатов identity (ADR-0020 §5)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.modules.identity.errors import (
    ConcurrentLoginError,
    SessionNotFoundError,
    UserNotFoundError,
)
from app.modules.identity.infrastructure.mappers import (
    apply_session,
    apply_user,
    session_to_domain,
    user_to_domain,
)
from app.modules.identity.infrastructure.models import (
    AuthIdentityRow,
    SessionRow,
    StatusHistoryRow,
    UserRow,
)
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import UserId

USER_CONSTRAINTS: ConstraintErrors = {
    "uq_auth_identities_provider_subject": ConcurrentLoginError,
}


class SqlUserRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def get(self, user_id: UserId) -> User:
        row = await self._load(UserRow.id == user_id)
        if row is None:
            raise UserNotFoundError(user_id=user_id)
        return self._tracked(user_to_domain(row))

    async def find_by_identity(self, provider: AuthProvider, subject: str) -> User | None:
        owner = select(AuthIdentityRow.user_id).where(
            AuthIdentityRow.provider == provider, AuthIdentityRow.subject == subject
        )
        row = await self._load(UserRow.id.in_(owner.scalar_subquery()))
        return self._tracked(user_to_domain(row)) if row is not None else None

    async def add(self, user: User) -> None:
        self._uow.require_active()
        row = UserRow(id=user.id, version=user.version, identities=[])
        apply_user(user, row)
        self._session.add(row)
        self._session.add_all(self._history_rows(user))
        await self._flush()
        self._uow.track(user)

    async def save(self, user: User) -> None:
        self._uow.require_active()
        row = await self._session.get(UserRow, user.id, options=[selectinload(UserRow.identities)])
        if row is None:
            raise UserNotFoundError(user_id=user.id)
        check_loaded_version(entity="user", loaded=row.version, expected=user.version)
        apply_user(user, row)
        row.version = user.version + 1
        self._session.add_all(self._history_rows(user))
        await self._flush()
        user.mark_persisted(version=row.version)
        self._uow.track(user)

    async def _load(self, condition: object) -> UserRow | None:
        stmt = (
            select(UserRow)
            .where(condition)  # type: ignore[arg-type]  # ColumnElement[bool] из вызывающего
            .options(selectinload(UserRow.identities))
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def _tracked(self, user: User) -> User:
        self._uow.track(user)
        return user

    def _history_rows(self, user: User) -> list[StatusHistoryRow]:
        return [
            StatusHistoryRow(
                user_id=user.id,
                from_status=change.from_.value,
                to_status=change.to.value,
                actor_id=change.actor_id,
                reason=change.reason,
                at=change.at,
            )
            for change in user.pull_history()
        ]

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, USER_CONSTRAINTS)


class SqlSessionRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def get_for_update(self, session_id: SessionId) -> Session:
        stmt = (
            select(SessionRow)
            .where(SessionRow.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SessionNotFoundError(session_id=session_id)
        session = session_to_domain(row)
        self._uow.track(session)
        return session

    async def add(self, session: Session) -> None:
        self._uow.require_active()
        row = SessionRow(id=session.id)
        apply_session(session, row)
        self._session.add(row)
        await self._session.flush()
        self._uow.track(session)

    async def save(self, session: Session) -> None:
        self._uow.require_active()
        row = await self._session.get(SessionRow, session.id)
        if row is None:
            raise SessionNotFoundError(session_id=session.id)
        apply_session(session, row)
        await self._session.flush()
        self._uow.track(session)
