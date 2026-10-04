"""Портфолио исполнителя (ARCHITECTURE §7.3, §10.1; DEVELOPMENT_PLAN 2.11): работы — фото или
ролик с подписью, по порядку.

В MVP работа — один файл (`portfolio_media` готова и к альбомам). Лимит — на профиль: до 60
фото и 6 роликов (ролик до 60 секунд проверяет media).

Модерация (DEVELOPMENT_PLAN 6.7, адаптер цели `portfolio`): новая работа — `pending`, её видит
только владелец (S37 «На проверке»); подпись проверяет конвейер текста, файл — проверка фото.
Решение публикует (`published` — работу видят S08 и S10) или скрывает (`rejected` — «Скрыто
модератором»). Правка подписи опубликованной работы — пост-модерация: работа остаётся видна.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.specialists.errors import InvalidPortfolioError, PortfolioFullError
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import MediaId, new_id

PortfolioItemId = NewType("PortfolioItemId", UUID)

MAX_CAPTION: Final = 120
"""Подпись работы — как название позиции прайса."""


class WorkKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


LIMITS: Final[Mapping[WorkKind, int]] = {WorkKind.IMAGE: 60, WorkKind.VIDEO: 6}
"""Работ на профиль (ADR-0007, §10.1): 60 фото и 6 роликов."""


class WorkStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


@dataclass(eq=False, kw_only=True)
class PortfolioItem(AggregateRoot):
    id: PortfolioItemId
    profile_id: UUID
    media_id: MediaId
    kind: WorkKind
    caption: str | None
    position: int
    status: WorkStatus
    created_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def add(
        cls,
        *,
        profile_id: UUID,
        media_id: MediaId,
        kind: WorkKind,
        caption: str | None,
        position: int,
        now: datetime,
    ) -> PortfolioItem:
        return cls(
            id=PortfolioItemId(new_id()),
            profile_id=profile_id,
            media_id=media_id,
            kind=kind,
            caption=_caption(caption),
            position=position,
            status=WorkStatus.PENDING,
            created_at=now,
        )

    @property
    def pending(self) -> bool:
        return self.status is WorkStatus.PENDING

    def approve(self) -> bool:
        """Проверка пройдена: ждавшая проверки — опубликована; скрытая автопроверкой (P0) —
        возвращена решением модератора. False — уже опубликована."""
        if self.status is WorkStatus.PUBLISHED:
            return False
        self.status = WorkStatus.PUBLISHED
        return True

    def reject(self) -> bool:
        """Нарушение: работа скрыта модератором (или автопроверкой при P0). False — уже."""
        if self.status is WorkStatus.REJECTED:
            return False
        self.status = WorkStatus.REJECTED
        return True

    def recaption(self, caption: str | None) -> bool:
        """Новая подпись; пустая — без подписи. False — та же."""
        value = _caption(caption)
        if value == self.caption:
            return False
        self.caption = value
        return True

    def remove(self, *, now: datetime) -> None:
        self.deleted_at = now


def ensure_room(kind: WorkKind, counts: Mapping[WorkKind, int]) -> None:
    """Место для ещё одной работы этого вида; нет — PortfolioFullError с лимитом."""
    limit = LIMITS[kind]
    if counts.get(kind, 0) >= limit:
        raise PortfolioFullError(kind=kind.value, limit=limit)


def _caption(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if len(text) > MAX_CAPTION:
        raise InvalidPortfolioError(field="caption")
    return text or None
