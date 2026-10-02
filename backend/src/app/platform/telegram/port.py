"""Порт отправки в Telegram (шаги 2.3a–2.3b, ARCHITECTURE §11.2, §12.4, ADR-0011).

Уведомление бота — HTML-текст (texts.py) и кнопки: web_app открывает Mini App на экране кода
deep link (buttons.py), callback — действие прямо в чате (callbacks.py, план 5.1). Адаптер —
aiogram_sender.py: перед вызовом Bot API занимает слот лимитера (25 msg/s на бота и 1 msg/s
на чат, limiter.py). Ответы Bot API — ошибки порта:
- 429 и слот дальше горизонта лимитера — RateLimitedError с `retry_after`: доставка ждёт,
  попытка не тратится;
- 403 (бот заблокирован, чата нет) — TelegramBlockedError: канал выключается;
- 400 — TelegramRejectedError: повтор не поможет;
- сеть и 5xx — ExternalServiceError: повтор задачи.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class AppButton:
    """Кнопка web_app: открывает Mini App по адресу с кодом deep link."""

    text: str
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CallbackButton:
    """Кнопка действия в чате: нажатие получает бот модуля (`data` — callbacks.py)."""

    text: str
    data: str


type Button = AppButton | CallbackButton


@dataclass(frozen=True, slots=True, kw_only=True)
class OutgoingMessage:
    chat_id: int
    """Личный чат с ботом. Не логируется (ADR-0020 §14)."""
    text: str
    """HTML: шаблон доверенный, параметры экранированы (texts.py)."""
    buttons: tuple[Button, ...] = ()
    """По одной кнопке в ряд."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SentMessage:
    message_id: int


class TelegramSender(Protocol):
    async def send(self, message: OutgoingMessage) -> SentMessage:
        """Отправить сообщение в чат. Недоступен Bot API — ExternalServiceError (повтор)."""
        ...


class TelegramBlockedError(Exception):
    """403: пользователь остановил бота (или чата больше нет) — писать некуда, пока он сам
    не запустит бота снова (/start, `my_chat_member`)."""


class TelegramRejectedError(Exception):
    """400: Bot API отверг сообщение (разметка, длина, кнопка) — повтор не поможет."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True, kw_only=True)
class Slot:
    wait: float
    """Через сколько секунд сообщению можно уйти."""
    reserved: bool
    """Слот за сообщением: отправить через `wait`. False — ждать дольше горизонта: слот не
    занят, попробовать снова ближе к сроку."""
    bot_pending: bool = False
    """Держал лимит чата: занят только слот чата, слот бота — `reserve_bot` в момент
    отправки."""


class SendLimiter(Protocol):
    """Скорость отправки бота (§11.2): 25 msg/s на бота, 1 msg/s на чат, пауза после 429."""

    async def reserve(self, chat_id: int, *, within: float) -> Slot:
        """Занять ближайший слот для сообщения в чат, если он не дальше `within` секунд."""
        ...

    async def reserve_bot(self, *, within: float) -> Slot:
        """Занять слот бота (после слота чата с `bot_pending`)."""
        ...

    async def pause(self, seconds: float) -> None:
        """Telegram ответил 429: всем отправкам бота — пауза."""
        ...
