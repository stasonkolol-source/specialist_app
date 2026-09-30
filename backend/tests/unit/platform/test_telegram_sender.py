"""Отправка в Telegram (DEVELOPMENT_PLAN 2.3b): токен-бакет и ответы Bot API.

Bot API подменён сессией, которая отвечает заданной ошибкой: сеть не нужна. Лимитер —
фейк; сам лимитер в Valkey проверяет tests/integration/test_telegram_limiter.py.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import (
    ClientDecodeError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Message

from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.telegram.aiogram_sender import HORIZON, AiogramTelegramSender
from app.platform.telegram.bucket import Bucket, advance, earliest
from app.platform.telegram.port import (
    AppButton,
    OutgoingMessage,
    Slot,
    TelegramBlockedError,
    TelegramRejectedError,
)
from app.platform.telegram.texts import BOT_DEFAULTS

pytestmark = pytest.mark.unit

MESSAGE = OutgoingMessage(
    chat_id=42,
    text="<b>Проверка</b>\nтекст",
    buttons=(AppButton(text="Открыть", url="https://app.test/?startapp=h"),),
)


# --- модель GCRA ----------------------------------------------------------------------------


def slots(bucket: Bucket, times: list[float]) -> list[float]:
    """Когда уйдут сообщения, пришедшие в `times`: каждое занимает ближайший слот."""
    tat: float | None = None
    sent = []
    for now in times:
        at = earliest(bucket, tat, now)
        tat = advance(bucket, tat, at)
        sent.append(at)
    return sent


def test_bot_bucket_lets_a_burst_of_25_through_then_every_40_ms() -> None:
    sent = slots(Bucket(rate=25, capacity=25), [1000.0] * 27)

    assert sent[:25] == [1000.0] * 25
    assert sent[25] == pytest.approx(1000.04)
    assert sent[26] == pytest.approx(1000.08)


def test_chat_bucket_spaces_messages_a_second_apart() -> None:
    sent = slots(Bucket(rate=1, capacity=1), [1000.0, 1000.0, 1000.0, 1010.0])

    assert sent == pytest.approx([1000.0, 1001.0, 1002.0, 1010.0])  # после паузы — сразу


def test_a_backlog_gets_exact_slots_in_one_pass() -> None:
    # 10 000 уведомлений разом: каждому — свой слот, никто не перебирается заново
    sent = slots(Bucket(rate=25, capacity=25), [0.0] * 10_000)

    assert sent[-1] == pytest.approx((10_000 - 25) / 25)
    assert sent == sorted(sent)


# --- адаптер aiogram ------------------------------------------------------------------------


@dataclass
class ScriptedSession(BaseSession):
    """Сессия Bot API: отвечает сообщением или заданной ошибкой."""

    error: Exception | None = None
    calls: list[TelegramMethod[Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура BaseSession
    ) -> Any:
        self.calls.append(method)
        if self.error is not None:
            raise self.error
        assert isinstance(method, SendMessage)
        return Message(
            message_id=777,
            date=datetime.now(UTC),
            chat=Chat(id=int(method.chat_id), type="private"),
            text=method.text,
        )

    async def stream_content(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[bytes]:  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None


@dataclass
class FakeLimiter:
    wait: float = 0.0
    reserved: list[int] = field(default_factory=list)
    paused: list[float] = field(default_factory=list)

    chat_bound: bool = False
    """Держит лимит чата: слот бота — отдельным вызовом."""

    async def reserve(self, chat_id: int, *, within: float) -> Slot:
        self.reserved.append(chat_id)
        return Slot(wait=self.wait, reserved=self.wait <= within, bot_pending=self.chat_bound)

    bot_wait: float = 0.0
    bot_reserved: int = 0

    async def reserve_bot(self, *, within: float) -> Slot:
        self.bot_reserved += 1
        return Slot(wait=self.bot_wait, reserved=self.bot_wait <= within)

    async def pause(self, seconds: float) -> None:
        self.paused.append(seconds)


def sender(
    error: Exception | None = None, wait: float = 0.0
) -> tuple[AiogramTelegramSender, ScriptedSession, FakeLimiter]:
    session = ScriptedSession(error=error)
    limiter = FakeLimiter(wait=wait)
    bot = Bot("123456:TEST", session=session, default=BOT_DEFAULTS)
    return AiogramTelegramSender(bot, limiter), session, limiter


CALL = SendMessage(chat_id=42, text="x")


async def test_sends_html_with_web_app_buttons() -> None:
    telegram, session, limiter = sender()

    sent = await telegram.send(MESSAGE)

    assert sent.message_id == 777
    assert limiter.reserved == [42]
    [call] = session.calls
    assert isinstance(call, SendMessage)
    assert (call.chat_id, call.text) == (42, MESSAGE.text)
    markup = call.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    [[button]] = markup.inline_keyboard
    assert button.web_app is not None
    assert (button.text, button.web_app.url) == ("Открыть", "https://app.test/?startapp=h")


async def test_near_slot_is_waited_for_in_place() -> None:
    telegram, session, _ = sender(wait=0.05)

    await telegram.send(MESSAGE)

    assert len(session.calls) == 1  # задача дождалась слота, а не ушла в очередь


async def test_far_slot_sends_the_delivery_back_to_the_queue() -> None:
    telegram, session, _ = sender(wait=HORIZON + 7.5)

    with pytest.raises(RateLimitedError) as caught:
        await telegram.send(MESSAGE)

    assert caught.value.retry_after == 8  # вернётся, когда до слота останется ≈ горизонт
    assert session.calls == []


async def test_flood_wait_pauses_every_sending() -> None:
    telegram, _, limiter = sender(
        TelegramRetryAfter(method=CALL, message="Too Many", retry_after=17)
    )

    with pytest.raises(RateLimitedError) as caught:
        await telegram.send(MESSAGE)

    assert caught.value.retry_after == 17
    assert limiter.paused == [17]


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(method=CALL, message="Forbidden: bot was blocked by the user"),
        TelegramBadRequest(method=CALL, message="Bad Request: chat not found"),
    ],
    ids=["blocked", "gone"],
)
async def test_blocked_bot_or_gone_chat(error: Exception) -> None:
    telegram, _, _ = sender(error)

    with pytest.raises(TelegramBlockedError):
        await telegram.send(MESSAGE)


async def test_bad_request_is_rejected_with_its_reason() -> None:
    telegram, _, _ = sender(TelegramBadRequest(method=CALL, message="Bad Request: can't parse"))

    with pytest.raises(TelegramRejectedError) as caught:
        await telegram.send(MESSAGE)

    assert caught.value.reason == "Bad Request: can't parse"


@pytest.mark.parametrize(
    "error",
    [
        TelegramNetworkError(method=CALL, message="timeout"),
        TelegramServerError(method=CALL, message="Bad Gateway"),
        ClientDecodeError("Failed to deserialize object", ValueError("html"), "<html>502</html>"),
    ],
    ids=["network", "5xx", "not-json"],
)
async def test_outage_is_retried(error: Exception) -> None:
    telegram, _, _ = sender(error)

    with pytest.raises(ExternalServiceError):
        await telegram.send(MESSAGE)


async def test_chat_bound_message_takes_the_bot_slot_when_it_goes() -> None:
    telegram, session, limiter = sender(wait=0.01)
    limiter.chat_bound = True

    await telegram.send(MESSAGE)

    assert (limiter.bot_reserved, len(session.calls)) == (1, 1)


async def test_busy_bot_after_the_chat_slot_sends_the_delivery_back() -> None:
    telegram, session, limiter = sender(wait=0.01)
    limiter.chat_bound, limiter.bot_wait = True, HORIZON + 2

    with pytest.raises(RateLimitedError):
        await telegram.send(MESSAGE)

    assert session.calls == []
