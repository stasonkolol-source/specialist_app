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


@dataclass(frozen=True, slots=True, kw_only=True)
class GoodsWaitlistJoined(DomainEvent):
    """Пользователь попросил сообщить о запуске раздела «Вещи» (S58, DEVELOPMENT_PLAN 7.5).

    Считается переход группы `goods_launch` из «выключено во всех каналах» во «включено хотя
    бы в одном»: повторное нажатие и сохранение S43 без изменений события не дают.
    `bot_writable` — может ли бот написать сейчас (без разрешения сообщим только в центре
    уведомлений). Подписчик — аналитика (сигнал спроса к точке решения 1, ADR-0019).
    """

    event_type = "notifications.GoodsWaitlistJoined"
    user_id: UserId
    bot_writable: bool
