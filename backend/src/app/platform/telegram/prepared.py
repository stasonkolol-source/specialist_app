"""Карточки для `WebApp.shareMessage` (DEVELOPMENT_PLAN 7.4, ADR-0011): `savePreparedInlineMessage`.

Inline mode боту для этого не нужен (проверено в 1.6, OWNER_CHECKLIST K5). Карточка живёт у
Telegram недолго, поэтому её готовят по нажатию «Поделиться». Любая ошибка Bot API — не ошибка
шаринга: без карточки клиент делится ссылкой, поэтому адаптер ждёт недолго и отвечает None.
Адрес и текст в лог не попадают (ADR-0020 §14).
"""

import structlog
from aiogram import Bot
from aiogram.exceptions import AiogramError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from app.platform.kernel.ids import new_id
from app.platform.telegram.port import ShareCard

log = structlog.get_logger(__name__)

TIMEOUT_SECONDS = 5
"""Человек ждёт окно выбора чата: дольше — делимся ссылкой."""


class AiogramPreparedMessages:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def prepare(self, telegram_user_id: int, card: ShareCard) -> str | None:
        button = InlineKeyboardButton(text=card.button_text, url=card.url)
        result = InlineQueryResultArticle(
            id=new_id().hex,
            title=card.title,
            description=card.description,
            input_message_content=InputTextMessageContent(message_text=card.text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
        )
        try:
            prepared = await self._bot.save_prepared_inline_message(
                user_id=telegram_user_id,
                result=result,
                allow_user_chats=True,
                allow_group_chats=True,
                allow_channel_chats=True,
                request_timeout=TIMEOUT_SECONDS,
            )
        except (AiogramError, TimeoutError) as exc:
            log.warning("share_prepare_failed", error=type(exc).__name__)
            return None
        return prepared.id


class NoPreparedMessages:
    """Тесты: Bot API не зовём — карточки нет, клиент делится ссылкой."""

    async def prepare(self, telegram_user_id: int, card: ShareCard) -> str | None:  # noqa: ARG002
        return None
