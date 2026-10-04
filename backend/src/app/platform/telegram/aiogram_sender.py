"""TelegramSender на aiogram `Bot` как HTTP-клиенте Bot API (шаг 2.3b, ADR-0011).

Перед вызовом — слот лимитера (limiter.py, `take_slot`). Слот ближе HORIZON — задача ждёт его
здесь же, не уходя из очереди; дальше — RateLimitedError, и доставка вернётся ближе к сроку, не
тратя попытку. Тот же `take_slot` — у фейка нагрузочного прогона (fake_sender.py). Ответы Bot
API переводятся в ошибки порта (port.py): 429 — пауза всем отправкам и RateLimitedError, 403 и
«chat not found» — TelegramBlockedError, прочие 400 — TelegramRejectedError, сеть, 5xx и
нечитаемый ответ (HTML-страница 502 вместо JSON) — ExternalServiceError. Адрес и текст в лог не
попадают (ADR-0020 §14).
"""

import asyncio
from collections.abc import Awaitable
from math import ceil

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    AiogramError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import DisabledButton, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.telegram.port import (
    Button,
    ButtonLine,
    CallbackButton,
    InactiveButton,
    OutgoingMessage,
    SendLimiter,
    SentMessage,
    Slot,
    TelegramBlockedError,
    TelegramRejectedError,
)

log = structlog.get_logger(__name__)

HORIZON = 3.0
"""Сколько секунд задача ждёт свой слот на месте: дольше — вернуться к сроку в очередь."""
GONE_CHAT = "chat not found"
NOT_MODIFIED = "message is not modified"
"""400 на правку кнопок, которые уже такие: повтор задачи — не ошибка."""
"""400 о чате, которого нет (пользователь удалил аккаунт Telegram): писать туда некуда."""
REASON_LENGTH = 200


class AiogramTelegramSender:
    def __init__(self, bot: Bot, limiter: SendLimiter) -> None:
        self._bot = bot
        self._limiter = limiter

    async def send(self, message: OutgoingMessage) -> SentMessage:
        await take_slot(self._limiter, message.chat_id)
        sent = await self._call(
            self._bot.send_message(
                chat_id=message.chat_id, text=message.text, reply_markup=keyboard(message.buttons)
            )
        )
        return SentMessage(message_id=sent.message_id)

    async def edit_buttons(
        self, chat_id: int, message_id: int, buttons: tuple[ButtonLine, ...]
    ) -> None:
        # правка — тоже вызов Bot API в чат: тот же лимитер, что у отправки
        await take_slot(self._limiter, chat_id)
        try:
            await self._call(
                self._bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=keyboard(buttons)
                )
            )
        except TelegramRejectedError as exc:
            if NOT_MODIFIED not in exc.reason.lower():
                raise

    async def _call[T](self, call: Awaitable[T]) -> T:
        """Вызов Bot API; его ответ-ошибка — ошибка порта (port.py)."""
        try:
            return await call
        except TelegramRetryAfter as exc:
            await self._limiter.pause(exc.retry_after)
            log.warning("telegram_flood_wait", retry_after=exc.retry_after)
            raise RateLimitedError(retry_after=max(1, exc.retry_after)) from exc
        except TelegramForbiddenError as exc:
            raise TelegramBlockedError from exc
        except TelegramBadRequest as exc:
            if GONE_CHAT in exc.message.lower():
                raise TelegramBlockedError from exc
            raise TelegramRejectedError(exc.message[:REASON_LENGTH]) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            raise ExternalServiceError(service="telegram", reason=type(exc).__name__) from exc
        except TelegramAPIError as exc:  # 401, 404, 409: наша конфигурация, а не адресат
            log.error("telegram_api_error", error=type(exc).__name__)
            raise ExternalServiceError(service="telegram", reason=type(exc).__name__) from exc
        except AiogramError as exc:  # ответ не JSON: страница прокси вместо Bot API
            raise ExternalServiceError(service="telegram", reason=type(exc).__name__) from exc


async def take_slot(limiter: SendLimiter, chat_id: int) -> None:
    """Дождаться слота лимитера для сообщения в чат (или RateLimitedError — в очередь)."""
    slot = await limiter.reserve(chat_id, within=HORIZON)
    await _wait(slot)
    if slot.bot_pending:  # ждали свой чат: теперь — слот бота
        await _wait(await limiter.reserve_bot(within=HORIZON))


async def _wait(slot: Slot) -> None:
    """Ждать занятый слот на месте; не занят — вернуться в очередь ближе к сроку."""
    if not slot.reserved:
        raise RateLimitedError(retry_after=max(1, ceil(slot.wait - HORIZON)))
    if slot.wait > 0:
        await asyncio.sleep(slot.wait)


def keyboard(lines: tuple[ButtonLine, ...]) -> InlineKeyboardMarkup | None:
    """Ряды кнопок порта — клавиатура aiogram (и для правки сообщения ботом модуля)."""
    if not lines:
        return None
    rows = [line if isinstance(line, tuple) else (line,) for line in lines]
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button(button) for button in row] for row in rows]
    )


def _button(button: Button) -> InlineKeyboardButton:
    if isinstance(button, CallbackButton):
        return InlineKeyboardButton(text=button.text, callback_data=button.data)
    if isinstance(button, InactiveButton):
        return InlineKeyboardButton(text=button.text, disabled=DisabledButton())
    return InlineKeyboardButton(text=button.text, web_app=WebAppInfo(url=button.url))
