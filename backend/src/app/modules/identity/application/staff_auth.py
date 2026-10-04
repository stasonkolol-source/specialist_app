"""StaffAuth (identity.api): вход персонала в админку и сессия (DEVELOPMENT_PLAN 2.7a).

Вход — логин, пароль (argon2) и код TOTP (±30 с); код одного шага второй раз не принимается.
Без роли, с удалённым аккаунтом или без верного кода — отказ без причины. Успешный вход пишется
в audit_log; лимит неудачных попыток — у входного адаптера (interfaces/admin/auth.py).
"""

import structlog

from app.modules.identity.api import StaffMember
from app.modules.identity.application.ports import (
    IdentityQuery,
    StaffCredential,
    StaffCredentials,
    StaffSecrets,
)
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

log = structlog.get_logger(__name__)


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
