"""Контракт модуля media для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из media только этот файл.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from app.modules.media.errors import MediaNotFoundError as MediaNotFoundError
from app.modules.media.errors import MediaStateError as MediaStateError
from app.platform.kernel.ids import MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaVariantRef:
    name: str
    """thumb, md, lg — по возрастанию ширины."""
    url: str
    width: int
    height: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaRef:
    """Файл, прикреплённый к объекту другого модуля (работа портфолио, фото профиля): как его
    показать. Пока файл обрабатывается, вариантов нет — экран рисует `placeholder` или заглушку."""

    id: MediaId
    kind: str
    """image | video."""
    status: str
    """uploaded | processing | ready | failed | rejected."""
    placeholder: str | None
    """ThumbHash (base64) для мгновенного превью."""
    variants: tuple[MediaVariantRef, ...]
    """WebP-варианты (у ролика — постер), когда файл готов."""
    video_url: str | None
    duration_ms: int | None


class MediaApi(Protocol):
    """Файлы для модулей выше по DAG: проверить перед прикреплением, показать, убрать."""

    async def owned(self, owner_id: UserId, media_id: MediaId, *, purpose: str) -> MediaRef:
        """Файл пользователя с этим назначением — для прикрепления. Чужой, удалённый или
        несуществующий — MediaNotFoundError (404); другое назначение, сбой или отказ обработки —
        MediaStateError (409)."""
        ...

    async def refs(self, media_ids: Collection[MediaId]) -> dict[MediaId, MediaRef]:
        """Как показать файлы; удалённых и несуществующих в ответе нет."""
        ...

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        """Удалить файл владельца: его убрали из портфолио или сменили фото профиля. Уже
        удалённый — ничего. Своя транзакция: вызывать после записи своей."""
        ...


class LegalHold(Protocol):
    """Удержание файлов (ADR-0016 §6): доказательства открытого кейса модерации (2.5a), а
    с 6.1c — и спора, не стираются, даже если автор удалил файл или аккаунт.

    Реализует модуль выше по DAG (moderation): media о нём не знает, связывает dishka.
    """

    async def held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        """Какие из файлов удерживаются сейчас. Читает в транзакции вызывающего."""
        ...
