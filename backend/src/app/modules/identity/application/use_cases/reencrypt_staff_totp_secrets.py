"""Перешифровать секреты TOTP персонала текущим ключом: `cli staff-totp-reencrypt` (шаг 8.4).

Нужен после смены APP_TOTP_KEY (прежний ключ — в APP_TOTP_KEY_PREVIOUS) и для строк до 8.4, где
секрет лежит открытым: все строки сразу, не дожидаясь входа каждого сотрудника. Повторный запуск
ничего не меняет. Строки, которые не расшифровать ни текущим, ни прежним ключом, не трогаем — их id
в итоге, сотруднику — заново `cli staff-create`. Секреты и шифротексты не пишутся ни в логи, ни в
аудит: сам вход сотрудника не меняется.
"""

from dataclasses import dataclass

import structlog

from app.modules.identity.application.dto import StaffTotpReencrypted
from app.modules.identity.application.ports import StaffCredentials, TotpSecretCipher
from app.platform.db.port import UnitOfWork

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReencryptStaffTotpSecretsCommand:
    """Без параметров: все строки сразу — персонала десятки."""


class ReencryptStaffTotpSecrets:
    def __init__(
        self, uow: UnitOfWork, credentials: StaffCredentials, cipher: TotpSecretCipher
    ) -> None:
        self._uow, self._credentials, self._cipher = uow, credentials, cipher

    async def __call__(
        self,
        cmd: ReencryptStaffTotpSecretsCommand,  # noqa: ARG002 — без параметров
    ) -> StaffTotpReencrypted:
        reencrypted = current = 0
        undecryptable = []
        async with self._uow:
            # одна транзакция под блокировкой строк: вход сотрудника ждёт её конца
            for user_id, stored in (await self._credentials.encrypted_totp_secrets()).items():
                totp = self._cipher.decrypt(stored, user_id)
                if totp is None:
                    undecryptable.append(user_id)
                elif totp.stale:
                    encrypted = self._cipher.encrypt(totp.value, user_id)
                    await self._credentials.replace_totp_secret(user_id, encrypted)
                    reencrypted += 1
                else:
                    current += 1
        log.info(
            "staff_totp_reencrypted",
            reencrypted=reencrypted,
            current=current,
            undecryptable=len(undecryptable),
        )
        return StaffTotpReencrypted(
            reencrypted=reencrypted, current=current, undecryptable=tuple(undecryptable)
        )
