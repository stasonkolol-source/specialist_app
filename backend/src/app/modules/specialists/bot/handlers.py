"""Бот specialists (DEVELOPMENT_PLAN 2.10): /available — «Доступен сегодня» прямо из чата.

Кнопки — варианты S38, ещё не прошедшие сегодня по Белграду, и «Выключить», если включено;
нажатие вызывает тот же SetAvailability, что и Mini App. Профиля нет — кнопка в Mini App: профиль
создаётся там (S32). Команды нет в меню бота: меню общее, а эта — только для специалистов.
"""

from datetime import datetime, time
from typing import Final

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.specialists.application.ports import ProfileQuery
from app.modules.specialists.application.use_cases.set_availability import (
    SetAvailability,
    SetAvailabilityCommand,
)
from app.modules.specialists.domain.profile import ProfileStatus
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import BUSINESS_TZ, Clock
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url, open_app_keyboard
from app.platform.telegram.texts import html_text, plain_text

HOURS: Final = (18, 20, 22)
"""Варианты S38 (AVAILABILITY_HOURS Mini App): «до 18:00», «до 20:00», «до 22:00»."""
AVAILABLE_CALLBACK: Final = "avail:"
OFF: Final = "off"


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(BUSINESS_TZ).strftime("%H:%M")


@inject
async def available(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    query: FromDishka[ProfileQuery],
    clock: FromDishka[Clock],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    if principal is None:  # чат есть, а аккаунта нет — сначала /start
        await message.answer(html_text(translator, "bot.language.need_start", locale))
        return
    profile = await query.of_user(principal.user_id)
    if profile is None or profile.status is not ProfileStatus.PUBLISHED:
        markup = None
        if telegram.mini_app_url:
            label = plain_text(translator, "bot.start.open", locale)
            markup = open_app_keyboard(mini_app_url(telegram.mini_app_url), label)
        await message.answer(
            html_text(translator, "bot.available.no_profile", locale), reply_markup=markup
        )
        return
    now = clock.now()
    on = profile.available_until is not None and profile.available_until > now
    hour_now = now.astimezone(BUSINESS_TZ).hour
    buttons = [
        InlineKeyboardButton(
            text=plain_text(translator, "bot.available.until", locale, time=f"{hour}:00"),
            callback_data=f"{AVAILABLE_CALLBACK}{hour}",
        )
        for hour in HOURS
        if hour_now < hour
    ]
    rows = [buttons] if buttons else []
    if on:
        off = plain_text(translator, "bot.available.turn_off", locale)
        rows.append([InlineKeyboardButton(text=off, callback_data=f"{AVAILABLE_CALLBACK}{OFF}")])
    if on and profile.available_until is not None:
        text = html_text(
            translator, "bot.available.on", locale, time=_hhmm(profile.available_until)
        )
    elif buttons:
        text = html_text(translator, "bot.available.off", locale)
    else:
        text = html_text(translator, "bot.available.late", locale)
    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    await message.answer(text, reply_markup=markup)


@inject
async def choose(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    set_availability: FromDishka[SetAvailability],
    principal: Principal | None = None,
) -> None:
    value = (callback.data or "").removeprefix(AVAILABLE_CALLBACK)
    if principal is None or (value != OFF and not value.isdigit()):
        await callback.answer()
        return
    until = None if value == OFF else time(int(value))
    profile = await set_availability(
        SetAvailabilityCommand(actor_id=principal.user_id, until=until)
    )
    if profile.available_until is None:
        done = html_text(translator, "bot.available.done_off", locale)
    else:
        done = html_text(
            translator, "bot.available.done_on", locale, time=_hhmm(profile.available_until)
        )
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(done)
        except TelegramBadRequest as exc:  # двойное нажатие: тот же текст Telegram отвергает
            if "message is not modified" not in exc.message:
                raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="specialists")
    private = F.chat.type == "private"
    router.message.register(available, Command("available"), private)
    router.callback_query.register(choose, F.data.startswith(AVAILABLE_CALLBACK))
    return router
