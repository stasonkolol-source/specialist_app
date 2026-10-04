"""Приглашение на «отзыв до платформы» (DEVELOPMENT_PLAN 7.6а; ARCHITECTURE §7.3, ADR-0016).

Специалист без отзывов просит прошлых клиентов рассказать о работе: одна ссылка — один клиент.
- приглашений не больше пяти на профиль: место занимает ссылка, по которой ждём отзыв, и
  использованная (отзыв снят модератором или стёрт — место не возвращается, иначе лимит
  обходится); истёкшая и отозванная место освобождают;
- ссылка живёт 30 дней; отозвать можно только неиспользованную;
- по ссылке пишут один отзыв; отозванная, истёкшая, использованная и несуществующая ссылка для
  чужого — одно и то же «не найдено», без подсказки почему.
Сам отзыв — `Review.pre_platform` (domain/review.py): отдельная метка, в рейтинг не входит.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.reviews.errors import (
    InvalidReviewError,
    ReviewInviteNotFoundError,
    ReviewInvitesFullError,
)
from app.platform.kernel.ids import UserId

MAX_INVITES: Final = 5
INVITE_TTL: Final = timedelta(days=30)
MAX_CLIENT_NAME: Final = 60
"""«Кому отправил» — заметка специалиста для себя, в списке S55."""


def new_token() -> UUID:
    """Секрет ссылки: UUID версии 4 из `secrets` — 122 случайных бита. Не new_id(): UUIDv7
    наполовину — время создания, для секрета он не годится."""
    return UUID(bytes=secrets.token_bytes(16), version=4)


class InviteStatus(StrEnum):
    """Строка списка S55: бейдж приглашения."""

    WAITING = "waiting"
    """«Ждём отзыв»: ссылка действует, отзыва нет — её можно отозвать."""
    EXPIRED = "expired"
    """Прошло 30 дней без отзыва: место свободно."""
    UNDER_REVIEW = "under_review"
    """«На модерации»: отзыв оставлен и ждёт модератора."""
    PUBLISHED = "published"
    REMOVED = "removed"
    """Отзыв снят модератором или стёрт вместе с аккаунтом автора."""


@dataclass(eq=False, kw_only=True)
class ReviewInvite:
    token: UUID
    """Секрет ссылки `ri_<base62>`: случайный UUIDv4, подбором не найти."""
    profile_id: UUID
    client_name: str | None
    created_at: datetime
    expires_at: datetime
    used_by: UserId | None = None
    used_at: datetime | None = None
    review_id: UUID | None = None

    @classmethod
    def issue(
        cls,
        *,
        token: UUID,
        profile_id: UUID,
        client_name: str | None,
        taken: int,
        now: datetime,
    ) -> ReviewInvite:
        """Новая ссылка; `taken` — сколько мест уже занято (`takes_slot`)."""
        if taken >= MAX_INVITES:
            raise ReviewInvitesFullError(limit=MAX_INVITES)
        name = (client_name or "").strip() or None
        if name is not None and len(name) > MAX_CLIENT_NAME:
            raise InvalidReviewError(field="client_name", reason="length")
        return cls(
            token=token,
            profile_id=profile_id,
            client_name=name,
            created_at=now,
            expires_at=now + INVITE_TTL,
        )

    @property
    def used(self) -> bool:
        return self.used_by is not None

    def usable(self, now: datetime) -> bool:
        """По ссылке ещё можно оставить отзыв."""
        return not self.used and now < self.expires_at

    def takes_slot(self, now: datetime) -> bool:
        """Занимает одно из пяти мест: ждёт отзыва или уже использована."""
        return self.used or now < self.expires_at

    def use(self, *, by: UserId, review_id: UUID, now: datetime) -> None:
        """Отзыв по ссылке оставлен: второй по ней не принять."""
        if not self.usable(now):
            raise ReviewInviteNotFoundError()
        self.used_by, self.used_at, self.review_id = by, now, review_id

    def status(self, review_status: str | None, now: datetime) -> InviteStatus:
        """Бейдж S55 по статусу отзыва (ReviewStatus), если он оставлен."""
        if not self.used:
            return InviteStatus.WAITING if now < self.expires_at else InviteStatus.EXPIRED
        if review_status == InviteStatus.PUBLISHED.value:
            return InviteStatus.PUBLISHED
        if review_status == InviteStatus.UNDER_REVIEW.value:
            return InviteStatus.UNDER_REVIEW
        return InviteStatus.REMOVED
