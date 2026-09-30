"""Порт отправки в Telegram (шаг 2.3a, ARCHITECTURE §11.2, ADR-0011).

Уведомление бота — HTML-текст (texts.py) и кнопки web_app: каждая открывает Mini App на
экране кода deep link (buttons.py). Адаптер на aiogram с лимитером 25 msg/s и 1 msg/s на
чат и разбором ответов (429 — пауза, 403 — канал выключен, 400 — без повтора) — шаг 2.3b;
до него — LoggingTelegramSender (logging_sender.py): сообщение не уходит.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class AppButton:
    """Кнопка web_app: открывает Mini App по адресу с кодом deep link."""

    text: str
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OutgoingMessage:
    chat_id: int
    """Личный чат с ботом. Не логируется (ADR-0020 §14)."""
    text: str
    """HTML: шаблон доверенный, параметры экранированы (texts.py)."""
    buttons: tuple[AppButton, ...] = ()
    """По одной кнопке в ряд."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SentMessage:
    message_id: int


class TelegramSender(Protocol):
    async def send(self, message: OutgoingMessage) -> SentMessage:
        """Отправить сообщение в чат. Недоступен Bot API — ExternalServiceError (повтор)."""
        ...
