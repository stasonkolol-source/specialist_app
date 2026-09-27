"""Бот identity (DEVELOPMENT_PLAN 0.22, ADR-0011): /start создаёт аккаунт и даёт кнопку Mini App."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.use_cases.register_telegram_user import (
    RegisterTelegramUser,
    RegisterTelegramUserCommand,
)
from app.platform.i18n.translator import Translator
from app.platform.observability.logging import bind_context
from app.platform.settings import TelegramSettings


def open_app_keyboard(url: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
    )


@inject
async def start(
    message: Message,
    register: FromDishka[RegisterTelegramUser],
    translator: FromDishka[Translator],
    telegram: FromDishka[TelegramSettings],
) -> None:
    author = message.from_user
    if author is None or author.is_bot:
        return
    profile = TelegramProfile(
        id=author.id,
        first_name=author.first_name,
        last_name=author.last_name,
        username=author.username,
        language_code=author.language_code,
        is_premium=bool(author.is_premium),
        allows_write_to_pm=True,  # пользователь сам начал диалог с ботом
    )
    user, is_new = await register(RegisterTelegramUserCommand(profile=profile))
    bind_context(user_id=str(user.id))
    key = "bot.start.welcome" if is_new else "bot.start.welcome_back"
    text = translator.text(key, user.ui_locale, name=user.display_name) or key
    url = telegram.mini_app_url
    markup = None
    if url:
        label = translator.text("bot.start.open", user.ui_locale) or "Open"
        markup = open_app_keyboard(url, label)
    await message.answer(text, reply_markup=markup)


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="identity")
    router.message.register(start, CommandStart(), F.chat.type == "private")
    return router
