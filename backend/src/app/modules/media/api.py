"""Контракт модуля media для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из media только этот файл.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
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
    """uploaded | processing | ready | failed | rejected. Отклонённый модерацией (6.7) — тоже
    `rejected`: для показа это одно и то же — показать нечего, файл не в счёт."""
    placeholder: str | None
    """ThumbHash (base64) для мгновенного превью."""
    variants: tuple[MediaVariantRef, ...]
    """WebP-варианты (у ролика — постер), когда файл готов и не отклонён модерацией."""
    video_url: str | None
    duration_ms: int | None

    @property
    def broken(self) -> bool:
        """Обработка не прошла (сбой или отказ): показать нечего, файл не в счёт."""
        return self.status in {"failed", "rejected"}


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageForCheck:
    """Фото на проверку модерацией (6.7): вариант `md` — 800 px по длинной стороне (у ролика —
    постер), уже без EXIF."""

    body: bytes
    content_type: str


class ModerationVerdict(StrEnum):
    """Итог проверки фото — published language (`media.assets.moderation_status`)."""

    APPROVED = "approved"
    FLAGGED = "flagged"
    """Ждёт модератора, фото видно."""
    REJECTED = "rejected"
    """Скрыто: не показывается, варианты — в приватном бакете."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaDuplicate:
    """Похожий файл другого владельца — по pHash (ADR-0016 L6): признак чужого фото."""

    media_id: MediaId
    owner_id: UserId
    distance: int
    """Сколько бит pHash различаются: 0 — тот же кадр, до 8 — пересжатая или чуть
    обрезанная копия."""


class MediaModeration(Protocol):
    """Итог проверки фото (6.7) без хранилища: решение модератора работает в любом процессе —
    и в боте, где S3 может быть не настроен (чат модераторов, 2.5b)."""

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        """Как `MediaApi.moderate`."""
        ...


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

    async def duplicates(self, media_id: MediaId) -> list[MediaDuplicate]:
        """Готовые файлы того же назначения у других владельцев с почти тем же pHash — ближние
        первыми, не больше пяти. Файл не готов, удалён или его назначению хэш не нужен (не
        портфолио) — пусто. Файлы того же владельца не в счёт: свой кадр дважды — не обман."""
        ...

    async def image_for_check(self, media_id: MediaId) -> ImageForCheck | None:
        """Готовое и ещё не проверенное фото (у ролика — постер) для модерации (6.7). None —
        проверять нечего: не готово, удалено, уже проверено или вариантов нет."""
        ...

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        """Записать итог проверки фото — в транзакции вызывающего. `rejected` прячет варианты
        (задача `media.hide_variants`), снятый отказ возвращает их (`media.restore_variants`).
        `auto` — автопроверка: только у ещё не проверенного файла. True — итог записан;
        False — файла нет, он не готов (удалён) или автопроверка опоздала."""
        ...

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        """Удалить файл владельца: его убрали из портфолио или сменили фото профиля. Задачей в
        транзакции вызывающего: файл удалится, только если запись прошла, а сбой удаления
        повторит воркер. Уже удалённый — ничего."""
        ...


class LegalHold(Protocol):
    """Удержание файлов (ADR-0016 §6): доказательства открытого кейса модерации (2.5a), а
    с 6.1c — и спора, не стираются, даже если автор удалил файл или аккаунт.

    Реализует модуль выше по DAG (moderation): media о нём не знает, связывает dishka.
    """

    async def held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        """Какие из файлов удерживаются сейчас. Читает в транзакции вызывающего."""
        ...
