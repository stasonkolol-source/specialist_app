"""Бот identity (DEVELOPMENT_PLAN 0.22, 1.6, ADR-0011): /start и /language.

/start создаёт аккаунт и отвечает кнопкой Mini App. Payload `/start <payload>` (ссылка
`t.me/<bot>?start=<код>`) уходит в `UserRegistered` — первое касание для атрибуции (growth),
а кнопка несёт тот же код в `?startapp=`: Mini App откроет экран ссылки. Сам /start публикует
`BotStarted` (notifications). /language меняет язык приложения и уведомлений (`ui_locale`).
Тексты — HTML (parse_mode бота), имена экранируются.
"""

from typing import Final

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.use_cases.register_telegram_user import (
    RegisterTelegramUser,
    RegisterTelegramUserCommand,
)
from app.modules.identity.application.use_cases.update_profile import (
    UpdateProfile,
    UpdateProfileCommand,
)
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.observability.logging import bind_context
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url, open_app_keyboard
from app.platform.telegram.texts import html_text, plain_text

LANGUAGES: Final[dict[Locale, str]] = {
    Locale.RU: "Русский",
    Locale.SR_LATN: "Srpski (latinica)",
    Locale.SR_CYRL: "Српски (ћирилица)",
}
"""Языки на выбор (English — «скоро», как на S02a). Названия — на самих языках и не
переводятся: sr-Latn каталога — транслит sr-Cyrl, а «ћирилица» транслитом не станет «latinica»."""
LANGUAGE_CALLBACK: Final = "lang:"


@inject
async def start(
    message: Message,
    command: CommandObject,
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
    user, is_new = await register(
        RegisterTelegramUserCommand(profile=profile, start_param=command.args)
    )
    bind_context(user_id=str(user.id))
    key = "bot.start.welcome" if is_new else "bot.start.welcome_back"
    text = html_text(translator, key, user.ui_locale, name=user.display_name)
    markup = None
    if telegram.mini_app_url:
        label = plain_text(translator, "bot.start.open", user.ui_locale)
        markup = open_app_keyboard(mini_app_url(telegram.mini_app_url, command.args), label)
    await message.answer(text, reply_markup=markup)


@inject
async def language(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    principal: Principal | None = None,
) -> None:
    if principal is None:  # чат есть, а аккаунта нет (сброшенная база dev) — сначала /start
        await message.answer(html_text(translator, "bot.language.need_start", locale))
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"{LANGUAGE_CALLBACK}{option}")]
            for option, name in LANGUAGES.items()
        ]
    )
    await message.answer(
        html_text(translator, "bot.language.prompt", locale), reply_markup=keyboard
    )


@inject
async def choose_language(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    update: FromDishka[UpdateProfile],
    principal: Principal | None = None,
) -> None:
    chosen = _chosen_locale(callback.data)
    if chosen is None or principal is None:
        await callback.answer()
        return
    await update(UpdateProfileCommand(actor_id=principal.user_id, ui_locale=chosen))
    done = html_text(translator, "bot.language.done", chosen, language=LANGUAGES[chosen])
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(done)


def _chosen_locale(data: str | None) -> Locale | None:
    """Язык из callback_data; чужое или устаревшее значение — None (данные шлёт клиент)."""
    value = (data or "").removeprefix(LANGUAGE_CALLBACK)
    return next((option for option in LANGUAGES if option.value == value), None)


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="identity")
    private = F.chat.type == "private"
    router.message.register(start, CommandStart(), private)
    router.message.register(language, Command("language"), private)
    router.callback_query.register(choose_language, F.data.startswith(LANGUAGE_CALLBACK))
    return router
