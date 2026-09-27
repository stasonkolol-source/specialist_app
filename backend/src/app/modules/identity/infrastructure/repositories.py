"""Репозитории identity (ADR-0020 §5): агрегаты и простые записи (согласия, санкции)."""

from collections.abc import Callable, Mapping
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.domain.consent import ConsentDocument
from app.modules.identity.domain.restriction import Restriction, RestrictionSource
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.modules.identity.errors import (
    ConcurrentLoginError,
    SessionNotFoundError,
    UnknownCityError,
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
    ConsentRow,
    RestrictionRow,
    SessionRow,
    StatusHistoryRow,
    UserRow,
)
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CaseId, RestrictionId, UserId, new_id
from app.platform.kernel.principal import Platform

USER_CONSTRAINTS: ConstraintErrors = {
    "uq_auth_identities_provider_subject": ConcurrentLoginError,
    "fk_users_home_city_id_cities": UnknownCityError,
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
        row = await self._load(UserRow.id.in_(owner.scalar_subquery()), lock=True)
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

    async def _load(self, condition: object, *, lock: bool = False) -> UserRow | None:
        stmt = (
            select(UserRow)
            .where(condition)  # type: ignore[arg-type]  # ColumnElement[bool] из вызывающего
            .options(selectinload(UserRow.identities))
            .execution_options(populate_existing=True)
        )
        if lock:
            # FOR NO KEY UPDATE — та же блокировка, что возьмёт UPDATE: входы одного человека
            # идут по очереди, а вставки в дочерние таблицы (FOR KEY SHARE по FK) не ждут
            stmt = stmt.with_for_update(of=UserRow, key_share=True)
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


class SqlConsentRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def grant(
        self,
        user_id: UserId,
        versions: Mapping[ConsentDocument, str],
        *,
        source: Platform,
        ip: str | None,
        now: datetime,
    ) -> int:
        self._uow.require_active()
        stmt = (
            insert(ConsentRow)
            .values(
                [
                    {
                        "id": new_id(),
                        "user_id": user_id,
                        "document": document,
                        "version": version,
                        "granted_at": now,
                        "source": source,
                        "ip": ip,
                    }
                    for document, version in versions.items()
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "document", "version"],
                index_where=text("withdrawn_at IS NULL"),
            )
            .returning(ConsentRow.id)
        )
        try:
            inserted = (await self._session.execute(stmt)).scalars().all()
        except IntegrityError as err:
            raise_domain_error(err, {"fk_consents_user_id_users": _user_not_found(user_id)})
        return len(inserted)


class SqlRestrictionRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def add(
        self,
        user_id: UserId,
        restriction: Restriction,
        *,
        source: RestrictionSource,
        case_id: CaseId | None,
        created_by: UserId | None,
    ) -> RestrictionId:
        self._uow.require_active()
        row = RestrictionRow(
            id=new_id(),
            user_id=user_id,
            kind=restriction.kind,
            reason_code=restriction.reason_code,
            source=source,
            case_id=case_id,
            starts_at=restriction.starts_at,
            ends_at=restriction.ends_at,
            created_by=created_by,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, {"fk_restrictions_user_id_users": _user_not_found(user_id)})
        return RestrictionId(row.id)


def _user_not_found(user_id: UserId) -> Callable[[], UserNotFoundError]:
    return lambda: UserNotFoundError(user_id=user_id)
