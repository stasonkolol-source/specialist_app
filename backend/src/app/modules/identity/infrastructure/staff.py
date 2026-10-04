"""Входы персонала (2.7a): identity.staff_credentials, argon2 (pwdlib) и TOTP (pyotp, RFC 6238)."""

from datetime import datetime
from typing import Final

import pyotp
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.application.ports import StaffCredential
from app.modules.identity.domain.user import UserStatus
from app.modules.identity.errors import StaffLoginTakenError
from app.modules.identity.infrastructure.models import StaffCredentialRow, UserRow
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

ISSUER: Final = "Sosedi admin"
TOTP_STEP: Final = 30
TOTP_WINDOW: Final = 1
"""Допуск в шагах по обе стороны: часы телефона могут отставать на полминуты."""


class SqlStaffCredentials:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def by_login(self, login: str) -> StaffCredential | None:
        return await self._one(func.lower(StaffCredentialRow.login) == login.lower(), lock=True)

    async def by_user(self, user_id: UserId) -> StaffCredential | None:
        return await self._one(StaffCredentialRow.user_id == user_id, lock=False)

    async def save(self, credential: StaffCredential) -> bool:
        self._uow.require_active()
        existed = await self._session.get(StaffCredentialRow, credential.user_id) is not None
        values = {
            "login": credential.login,
            "password_hash": credential.password_hash,
            "totp_secret": credential.totp_secret,
            "totp_last_step": None,
        }
        stmt = (
            insert(StaffCredentialRow)
            .values(user_id=credential.user_id, **values)
            .on_conflict_do_update(
                index_elements=[StaffCredentialRow.user_id],
                set_={**values, "updated_at": func.now()},
            )
        )
        try:
            async with self._session.begin_nested():
                await self._session.execute(stmt)
        except IntegrityError as err:
            raise_domain_error(err, {"uq_staff_credentials_login": StaffLoginTakenError})
        return existed

    async def use_step(self, user_id: UserId, step: int) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(StaffCredentialRow)
            .where(StaffCredentialRow.user_id == user_id)
            .values(totp_last_step=step)
        )

    async def _one(self, condition: object, *, lock: bool) -> StaffCredential | None:
        stmt = (
            select(StaffCredentialRow)
            .join(UserRow, UserRow.id == StaffCredentialRow.user_id)
            .where(condition, UserRow.status != UserStatus.DELETED)  # type: ignore[arg-type]
        )
        if lock:
            stmt = stmt.with_for_update(of=StaffCredentialRow)
        row = (await self._session.scalars(stmt)).first()
        if row is None:
            return None
        return StaffCredential(
            user_id=UserId(row.user_id),
            login=row.login,
            password_hash=row.password_hash,
            totp_secret=row.totp_secret,
            totp_last_step=row.totp_last_step,
        )


class PwdlibStaffSecrets:
    """argon2id (параметры pwdlib по умолчанию) и TOTP: 6 цифр, шаг 30 с, SHA-1 — совместимо с
    Google Authenticator, 1Password, Aegis."""

    def __init__(self) -> None:
        self._hasher = PasswordHash((Argon2Hasher(),))
        self._dummy = self._hasher.hash("dummy-password-for-timing")

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password, password_hash)
        except PwdlibError:
            return False

    def dummy_verify(self) -> None:
        self._hasher.verify("wrong-password", self._dummy)

    def new_totp_secret(self) -> str:
        return pyotp.random_base32()

    def totp_uri(self, secret: str, login: str) -> str:
        return pyotp.TOTP(secret, interval=TOTP_STEP).provisioning_uri(
            name=login, issuer_name=ISSUER
        )

    def totp_step(self, secret: str, code: str, now: datetime) -> int | None:
        if not code.isdigit() or len(code) != 6:
            return None
        totp = pyotp.TOTP(secret, interval=TOTP_STEP)
        current = int(now.timestamp()) // TOTP_STEP
        for step in range(current - TOTP_WINDOW, current + TOTP_WINDOW + 1):
            if pyotp.utils.strings_equal(totp.generate_otp(step), code):
                return step
        return None
