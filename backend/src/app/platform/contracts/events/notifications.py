"""События модуля notifications (ADR-0020 §2)."""

from dataclasses import dataclass

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteAccessGranted(DomainEvent):
    """Бот может писать пользователю: канал `telegram` появился или снова включился.

    Повтор при доступном канале события не даёт — считается переход в «можно писать».
    `via` — как разрешили: `bot_start` (/start в боте) или `mini_app` (requestWriteAccess).
    Подписчик — аналитика (метрика «Opt-in уведомлений», 1.7).
    """

    event_type = "notifications.WriteAccessGranted"
    user_id: UserId
    via: str
