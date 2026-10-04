"""Вход персонала в админку (DEVELOPMENT_PLAN 2.7a; ADR-0009, ARCHITECTURE §13.2).

- `cli staff-create` — пароль (вводится в терминале) и новый секрет TOTP сотруднику с ролью из
  `identity.user_roles` (`cli staff-grant`); повторный вызов заменяет и пароль, и TOTP. Секрет
  показывается один раз, в логи и аудит не попадает.
- Вход — логин, пароль (argon2) и код TOTP (±30 с); код одного шага второй раз не принимается.
  Без роли, с удалённым аккаунтом или без верного кода — отказ без причины. Успешный вход пишется
  в audit_log; лимит неудачных попыток — у входного адаптера (interfaces/admin/auth.py).
"""

import re
from dataclasses import dataclass
from typing import Final

import structlog

from app.modules.identity.api import StaffMember
from app.modules.identity.application.dto import StaffCredentialsSet
from app.modules.identity.application.ports import (
    IdentityQuery,
    StaffCredential,
    StaffCredentials,
    StaffSecrets,
    UserRepository,
)
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.modules.identity.errors import InvalidStaffLoginError, NotStaffError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

log = structlog.get_logger(__name__)

LOGIN_RE: Final = re.compile(r"[a-z0-9._-]{3,64}")
MIN_PASSWORD: Final = 12


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateStaffLoginCommand:
    telegram_id: int
    """Кто: сотрудник по Telegram id (в логи не пишется)."""
    login: str
    password: str


class CreateStaffLogin:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        query: IdentityQuery,
        credentials: StaffCredentials,
        secrets: StaffSecrets,
        audit: AuditLog,
    ) -> None:
        self._uow, self._users, self._query = uow, users, query
        self._credentials, self._secrets, self._audit = credentials, secrets, audit

    async def __call__(self, cmd: CreateStaffLoginCommand) -> StaffCredentialsSet | None:
        """None — такого пользователя нет (не открывал бот или Mini App) или он удалён."""
        login = cmd.login.strip().lower()
        if not LOGIN_RE.fullmatch(login) or len(cmd.password) < MIN_PASSWORD:
            raise InvalidStaffLoginError(min_password=MIN_PASSWORD)
        password_hash = self._secrets.hash_password(cmd.password)
        secret = self._secrets.new_totp_secret()
        async with self._uow:
            user = await self._users.find_by_identity(AuthProvider.TELEGRAM, str(cmd.telegram_id))
            if user is None or user.status is UserStatus.DELETED:
                return None
            if not await self._query.roles(user.id):
                raise NotStaffError()
            replaced = await self._credentials.save(
                StaffCredential(
                    user_id=user.id,
                    login=login,
                    password_hash=password_hash,
                    totp_secret=secret,
                    totp_last_step=None,
                )
            )
            await self._audit.record(
                AuditEntry(
                    action="identity.staff.credentials_set",
                    actor_kind=ActorKind.SYSTEM,
                    entity_type="identity.user",
                    entity_id=user.id,
                    changes={"login": login, "replaced": replaced},
                )
            )
        return StaffCredentialsSet(
            user_id=user.id,
            login=login,
            totp_secret=secret,
            totp_uri=self._secrets.totp_uri(secret, login),
            replaced=replaced,
        )


class StaffAuthService:
    """StaffAuth (identity.api) — вход и сессия админки."""

    def __init__(
        self,
        uow: UnitOfWork,
        query: IdentityQuery,
        credentials: StaffCredentials,
        secrets: StaffSecrets,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._query = uow, query
        self._credentials, self._secrets = credentials, secrets
        self._audit, self._clock = audit, clock

    async def authenticate(
        self, login: str, password: str, code: str, *, ip: str | None = None
    ) -> StaffMember | None:
        async with self._uow:
            found = await self._credentials.by_login(login.strip().lower())
            if found is None:
                self._secrets.dummy_verify()
                return None
            if not self._secrets.verify_password(password, found.password_hash):
                return None
            step = self._secrets.totp_step(found.totp_secret, code.strip(), self._clock.now())
            if step is None or (found.totp_last_step is not None and step <= found.totp_last_step):
                return None
            member = await self._member(found)
            if member is None:
                return None
            await self._credentials.use_step(found.user_id, step)
            await self._audit.record(
                AuditEntry(
                    action="identity.staff.login",
                    actor_kind=ActorKind.STAFF,
                    actor_id=member.user_id,
                    entity_type="identity.user",
                    entity_id=member.user_id,
                    ip=ip,
                )
            )
        log.info("staff_login", user_id=str(member.user_id))
        return member

    async def member(self, user_id: UserId) -> StaffMember | None:
        found = await self._credentials.by_user(user_id)
        return None if found is None else await self._member(found)

    async def _member(self, found: StaffCredential) -> StaffMember | None:
        roles = await self._query.roles(found.user_id)
        if not roles:
            return None
        return StaffMember(user_id=found.user_id, login=found.login, roles=roles)
