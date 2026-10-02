"""Удаление аккаунта по запросу (ARCHITECTURE §7.10, ADR-0018, DEVELOPMENT_PLAN 2.12).

Запрос ставит grace-период 7 дней: до исполнения его можно отменить. Исполняет задача
`identity.process_deletions` — обезличивает аккаунт (`User.forget`) и публикует `UserDeleted`,
а модули выше по DAG удаляют своё. Аккаунт с открытым кейсом модерации ждёт решения: «жалобы
удалим после их решения» (S45).

Способы входа удалённого аккаунта остаются только хэшем HMAC на 12 месяцев: повторная
регистрация тем же Telegram (или телефоном) становится сигналом риска — так рейтинг и санкции
не «отмываются» удалением. Данные при этом не восстанавливаются.
"""

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import UserId, new_id

DeletionRequestId = NewType("DeletionRequestId", UUID)

GRACE_PERIOD: Final = timedelta(days=7)
"""Сколько ждёт запрос: передумавший открывает приложение и отменяет."""
HASH_RETENTION: Final = timedelta(days=365)
"""Сколько хранится хэш способа входа удалённого аккаунта (матрица сроков §7.10)."""


class DeletionSource(StrEnum):
    """Откуда пришёл запрос: Mini App, бот, приложения, веб, поддержка по обращению."""

    TMA = "tma"
    BOT = "bot"
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
    SUPPORT = "support"


class HashKind(StrEnum):
    TELEGRAM = "telegram"
    PHONE = "phone"


_PREFIX: Final = {HashKind.TELEGRAM: "tg", HashKind.PHONE: "phone"}


def identity_hash(key: bytes, kind: HashKind, value: str) -> bytes:
    """HMAC-SHA256 способа входа: `tg:<telegram id>` или `phone:<e164>`. Ключ — постоянный
    секрет (`APP_HASH_KEY`): без него по хэшу не подобрать исходное значение."""
    return hmac.new(key, f"{_PREFIX[kind]}:{value}".encode(), hashlib.sha256).digest()


def login_hashes(
    key: bytes, *, telegram_ids: Iterable[str], phone: str | None
) -> dict[bytes, HashKind]:
    """Хэши способов входа удаляемого аккаунта: Telegram ID и телефон, если он был."""
    hashes = {
        identity_hash(key, HashKind.TELEGRAM, value): HashKind.TELEGRAM for value in telegram_ids
    }
    if phone:
        hashes[identity_hash(key, HashKind.PHONE, phone)] = HashKind.PHONE
    return hashes


@dataclass(eq=False, kw_only=True)
class DeletionRequest(AggregateRoot):
    id: DeletionRequestId
    user_id: UserId
    source: DeletionSource
    requested_at: datetime
    execute_after: datetime
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def request(cls, user_id: UserId, *, source: DeletionSource, now: datetime) -> DeletionRequest:
        return cls(
            id=DeletionRequestId(new_id()),
            user_id=user_id,
            source=source,
            requested_at=now,
            execute_after=now + GRACE_PERIOD,
        )

    @property
    def active(self) -> bool:
        """Ждёт исполнения: не отменён и не исполнен."""
        return self.cancelled_at is None and self.completed_at is None

    def due(self, now: datetime) -> bool:
        return self.active and now >= self.execute_after

    def cancel(self, *, now: datetime) -> None:
        if self.active:
            self.cancelled_at = now

    def complete(self, *, now: datetime) -> None:
        if self.active:
            self.completed_at = now
