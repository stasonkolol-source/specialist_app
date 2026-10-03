"""Представления reviews для экранов (S28 «Мои отзывы») — из query-сервиса (ADR-0020 §4)."""

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
