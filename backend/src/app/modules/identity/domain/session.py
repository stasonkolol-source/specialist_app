"""Refresh-сессия и детектор кражи (ADR-0009, docs/spikes/0.14-initdata-jwt.md п. 7).

В сессии — хэш текущего секрета refresh, хэш предыдущего и время ротации:
- совпал текущий → ротация: новый хэш, предыдущий запоминается, срок продлевается;
- совпал предыдущий не позже RACE_WINDOW после ротации → RACE: 401 без отзыва
  (ответ на прошлый запрос потерялся или два обновления пришли одновременно);
- иначе → REUSED: сессия отзывается целиком, use case кладёт sid в denylist.
Отозванная или истёкшая сессия — ошибка без изменений.
"""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NewType
from uuid import UUID

from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Platform
from app.platform.security.errors import InvalidRefreshTokenError, SessionRevokedError

SessionId = NewType("SessionId", UUID)
RACE_WINDOW = timedelta(seconds=10)


class RefreshOutcome(StrEnum):
    ROTATED = "rotated"
    RACE = "race"
    REUSED = "reused"


class RevokeReason(StrEnum):
    LOGOUT = "logout"
    REFRESH_REUSED = "refresh_reused"
    RESTRICTED = "restricted"
    ACCOUNT_DELETED = "account_deleted"


@dataclass(eq=False, kw_only=True)
class Session(AggregateRoot):
    id: SessionId
    user_id: UserId
    platform: Platform
    bot_id: int | None
    amr: tuple[str, ...]
    """Способ входа (`tg_webapp`, …): переходит в клейм `amr` при каждом refresh."""
    refresh_hash: bytes
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    previous_refresh_hash: bytes | None = None
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: RevokeReason | None = None

    @classmethod
    def open(
        cls,
        *,
        user_id: UserId,
        platform: Platform,
        bot_id: int | None,
        amr: tuple[str, ...],
        refresh_hash: bytes,
        now: datetime,
        ttl: timedelta,
        session_id: SessionId | None = None,
    ) -> Session:
        return cls(
            id=session_id or SessionId(new_id()),
            user_id=user_id,
            platform=platform,
            bot_id=bot_id,
            amr=amr,
            refresh_hash=refresh_hash,
            created_at=now,
            last_used_at=now,
            expires_at=now + ttl,
        )

    def refresh(
        self, *, presented_hash: bytes, new_hash: bytes, now: datetime, ttl: timedelta
    ) -> RefreshOutcome:
        if self.revoked_at is not None:
            raise SessionRevokedError
        if now >= self.expires_at:
            raise InvalidRefreshTokenError
        if hmac.compare_digest(presented_hash, self.refresh_hash):
            self.previous_refresh_hash, self.refresh_hash = self.refresh_hash, new_hash
            self.rotated_at = self.last_used_at = now
            self.expires_at = now + ttl
            return RefreshOutcome.ROTATED
        if self._in_race_window(presented_hash, now):
            return RefreshOutcome.RACE
        self.revoke(reason=RevokeReason.REFRESH_REUSED, now=now)
        return RefreshOutcome.REUSED

    def revoke(self, *, reason: RevokeReason, now: datetime) -> None:
        """Отозвать сессию; повторный отзыв ничего не меняет."""
        if self.revoked_at is None:
            self.revoked_at = now
            self.revoke_reason = reason

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at

    @property
    def sid(self) -> str:
        """Идентификатор сессии в JWT (`sid`) и в refresh-токене."""
        return self.id.hex

    def _in_race_window(self, presented_hash: bytes, now: datetime) -> bool:
        return (
            self.previous_refresh_hash is not None
            and self.rotated_at is not None
            and now - self.rotated_at <= RACE_WINDOW
            and hmac.compare_digest(presented_hash, self.previous_refresh_hash)
        )
