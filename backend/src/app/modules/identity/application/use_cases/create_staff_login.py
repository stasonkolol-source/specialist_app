"""Вход персонала в админку: `cli staff-create` (DEVELOPMENT_PLAN 2.7a; ADR-0009, §13.2).

Пароль (вводится в терминале) и новый секрет TOTP — сотруднику с ролью из `identity.user_roles`
(`cli staff-grant`); повторный вызов заменяет и пароль, и TOTP. Секрет показывается один раз, в
логи и аудит не попадает, в БД ложится зашифрованным (8.4). Сам вход — application/staff_auth.py.
"""

import re
from dataclasses import dataclass
from typing import Final

from app.modules.identity.application.dto import StaffCredentialsSet
from app.modules.identity.application.ports import (
    IdentityQuery,
    StaffCredential,
    StaffCredentials,
    StaffSecrets,
    TotpSecretCipher,
    UserRepository,
)
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.modules.identity.errors import InvalidStaffLoginError, NotStaffError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork

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
        cipher: TotpSecretCipher,
        audit: AuditLog,
    ) -> None:
        self._uow, self._users, self._query = uow, users, query
        self._credentials, self._secrets, self._cipher = credentials, secrets, cipher
        self._audit = audit

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
                    encrypted_totp_secret=self._cipher.encrypt(secret, user.id),
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
