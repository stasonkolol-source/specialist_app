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
