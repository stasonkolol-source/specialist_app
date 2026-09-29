"""События модуля media (ADR-0020 §2)."""

from dataclasses import dataclass

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaUploaded(DomainEvent):
    """Файл целиком в хранилище и совпал с заявленным (`uploaded`).

    Подписчик — обработка `media.process` в очереди `media` (шаг 2.2). `kind` (`image`,
    `video`, `document`) и `purpose` (`avatar`, `portfolio`, `job`, …) — published language.
    """

    event_type = "media.MediaUploaded"
    media_id: MediaId
    owner_id: UserId
    kind: str
    purpose: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaReady(DomainEvent):
    """Файл обработан (`ready`): варианты без EXIF лежат в бакете media (шаг 2.2).

    Подписчики — привязка к профилю или заявке (2.8a, 5.1) и автомодерация (2.6).
    """

    event_type = "media.MediaReady"
    media_id: MediaId
    owner_id: UserId
    kind: str
    purpose: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaRejected(DomainEvent):
    """Обработка не приняла файл (`rejected`): не картинка по magic bytes, слишком много
    пикселей (decompression bomb), не читается. `reason` — код причины."""

    event_type = "media.MediaRejected"
    media_id: MediaId
    owner_id: UserId
    purpose: str
    reason: str
