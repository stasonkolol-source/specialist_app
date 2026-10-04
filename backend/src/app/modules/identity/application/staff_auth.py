"""StaffAuth (identity.api): вход персонала в админку и сессия (DEVELOPMENT_PLAN 2.7a).

Вход — логин, пароль (argon2) и код TOTP (±30 с); код одного шага второй раз не принимается.
Без роли, с удалённым аккаунтом или без верного кода — отказ без причины. Успешный вход пишется
в audit_log; лимит неудачных попыток — у входного адаптера (interfaces/admin/auth.py).
Секрет TOTP в БД зашифрован (8.4): не расшифровать — входа нет; секрет под прежним ключом или
открытый (строка до 8.4) удачный вход перешифровывает текущим ключом. Сессия держит поколение
входа (`session_epoch`): `cli staff-create` (новые пароль и TOTP) и `cli staff-revoke` его
увеличивают, и cookie, выданные раньше, больше не действуют (cookie подписана, но не хранится).
"""

import structlog

from app.modules.identity.api import StaffMember
from app.modules.identity.application.ports import (
    IdentityQuery,
    StaffCredential,
    StaffCredentials,
    StaffSecrets,
    TotpSecretCipher,
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
        cipher: TotpSecretCipher,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._query = uow, query
        self._credentials, self._secrets, self._cipher = credentials, secrets, cipher
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
            totp = self._cipher.decrypt(found.encrypted_totp_secret, found.user_id)
            if totp is None:
                # ключ не тот (ротация без APP_TOTP_KEY_PREVIOUS) или строка испорчена — без
                # секрета и шифротекста в логе; сотруднику — заново `cli staff-create`
                log.warning("staff_totp_undecryptable", user_id=str(found.user_id))
                return None
            step = self._secrets.totp_step(totp.value, code.strip(), self._clock.now())
            if step is None or (found.totp_last_step is not None and step <= found.totp_last_step):
                return None
            member = await self._member(found)
            if member is None:
                return None
            await self._credentials.use_step(found.user_id, step)
            if totp.stale:
                await self._credentials.replace_totp_secret(
                    found.user_id, self._cipher.encrypt(totp.value, found.user_id)
                )
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

    async def member(self, user_id: UserId, session_epoch: int) -> StaffMember | None:
        found = await self._credentials.by_user(user_id)
        if found is None or found.session_epoch != session_epoch:
            return None  # пароль и TOTP заменены или сессии отозваны — войти заново
        return await self._member(found)

    async def _member(self, found: StaffCredential) -> StaffMember | None:
        roles = await self._query.roles(found.user_id)
        if not roles:
            return None
        return StaffMember(
            user_id=found.user_id,
            login=found.login,
            roles=roles,
            session_epoch=found.session_epoch,
        )
