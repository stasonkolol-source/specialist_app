"""Представления reviews для экранов (S28 «Мои отзывы», S55 «Отзывы до платформы») — из
query-сервиса (ADR-0020 §4)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.platform.kernel.ids import DealId, UserId


class ReviewsDirection(StrEnum):
    RECEIVED = "received"
    """Обо мне: опубликованные."""
    WRITTEN = "written"
    """Мои: в любом статусе, кроме стёртых."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UserReview:
    """Отзыв в «Моих отзывах»: вторая сторона — автор (полученные) или тот, о ком (написанные)."""

    id: UUID
    kind: str
    """ReviewKind: `deal` или `pre_platform` (7.6а)."""
    work_title: str | None
    """«Что делал мастер» — у отзыва до платформы."""
    deal_id: DealId | None
    counterpart_id: UserId
    rating: int
    criteria: Mapping[str, int]
    body: str | None
    status: str
    reply_body: str | None
    reply_status: str | None
    reply_at: datetime | None
    created_at: datetime
    published_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteListing:
    """Приглашение в списке S55 со статусом своего отзыва (если он оставлен)."""

    token: UUID
    client_name: str | None
    created_at: datetime
    expires_at: datetime
    used_by: UserId | None
    used_at: datetime | None
    review_id: UUID | None
    review_status: str | None
    """ReviewStatus отзыва по ссылке; стёртый автором — `removed`."""
    rating: int | None
    published_at: datetime | None
