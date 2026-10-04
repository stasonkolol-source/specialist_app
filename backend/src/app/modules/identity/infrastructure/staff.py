"""Входы персонала (2.7a): identity.staff_credentials, argon2 (pwdlib) и TOTP (pyotp, RFC 6238).

Секрет TOTP в БД зашифрован ключом APP_TOTP_KEY (8.4, `AesGcmTotpCipher`)."""

import re
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

from app.modules.identity.application.ports import StaffCredential, TotpSecret
from app.modules.identity.domain.user import UserStatus
from app.modules.identity.errors import StaffLoginTakenError
from app.modules.identity.infrastructure.models import StaffCredentialRow, UserRow
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId
from app.platform.security.secretbox import SealedSecretError, SecretBox, is_sealed

ISSUER: Final = "Sosedi admin"
TOTP_STEP: Final = 30
TOTP_WINDOW: Final = 1
"""Допуск в шагах по обе стороны: часы телефона могут отставать на полминуты."""
PLAIN_TOTP_SECRET: Final = re.compile(r"[A-Z2-7]{16,}=*")
"""Секрет pyotp (base32) открытым текстом — так лежали строки до 8.4."""


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
            "totp_secret": credential.encrypted_totp_secret,
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

    async def replace_totp_secret(self, user_id: UserId, encrypted_totp_secret: str) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(StaffCredentialRow)
            .where(StaffCredentialRow.user_id == user_id)
            .values(totp_secret=encrypted_totp_secret)
        )

    async def encrypted_totp_secrets(self) -> dict[UserId, str]:
        self._uow.require_active()
        rows = await self._session.execute(
            select(StaffCredentialRow.user_id, StaffCredentialRow.totp_secret).with_for_update()
        )
        return {UserId(user_id): secret for user_id, secret in rows}

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
            encrypted_totp_secret=row.totp_secret,
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


class AesGcmTotpCipher:
    """Секрет TOTP в БД — AES-256-GCM под APP_TOTP_KEY (`SecretBox`); шифротекст привязан к
    сотруднику: перенесённый в чужую строку не расшифруется. Строка до 8.4 (открытый base32)
    читается и помечается к перешифровке; всё остальное, что не расшифровать, — отказ."""

    def __init__(self, box: SecretBox) -> None:
        self._box = box

    def encrypt(self, secret: str, user_id: UserId) -> str:
        return self._box.seal(secret, context=_context(user_id))

    def decrypt(self, stored: str, user_id: UserId) -> TotpSecret | None:
        if not is_sealed(stored):
            plain = PLAIN_TOTP_SECRET.fullmatch(stored) is not None
            return TotpSecret(value=stored, stale=True) if plain else None
        try:
            opened = self._box.open(stored, context=_context(user_id))
        except SealedSecretError:
            return None
        return TotpSecret(value=opened.plaintext, stale=opened.stale)


def _context(user_id: UserId) -> str:
    return f"identity.staff_credentials.totp_secret:{user_id}"
