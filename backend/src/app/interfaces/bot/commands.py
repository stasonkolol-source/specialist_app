"""Общие команды бота (DEVELOPMENT_PLAN 1.6, PRODUCT «Telegram-бот»): /app, /help, /terms,
/privacy и ответ на всё, что бот не понял.

Команды модулей живут в modules/<m>/bot (/start и /language — identity). Эти не принадлежат
модулю: они открывают Mini App и справку. Роутер подключается последним (create_dispatcher):
ответ на непонятное сообщение получает только то, что не взяли модули.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.platform.config.port import LegalVersions
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.legal.port import LegalDocument, LegalLibrary
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import link_keyboard, mini_app_url, open_app_keyboard
from app.platform.telegram.deeplinks import LinkDocument, LinkType, StartLink, encode_start_param
from app.platform.telegram.texts import html_text, plain_text

DATE_FORMAT = "%d.%m.%Y"
"""Дата редакции цифрами: без падежей («от 27.09.2026», «од 27.09.2026»)."""


@inject
async def app_command(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    telegram: FromDishka[TelegramSettings],
) -> None:
    await message.answer(
        html_text(translator, "bot.app.text", locale),
        reply_markup=_open_app(translator, telegram, locale, "bot.start.open"),
    )


@inject
async def help_command(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    telegram: FromDishka[TelegramSettings],
) -> None:
    parts = [html_text(translator, "bot.help.text", locale)]
    markup = None
    if telegram.support_username:
        parts.append(html_text(translator, "bot.help.support", locale))
        markup = link_keyboard(
            f"https://t.me/{telegram.support_username}",
            plain_text(translator, "bot.help.support_button", locale),
        )
    else:  # K23 и Q25 не решены: контакт поддержки появится, когда владелец его даст
        parts.append(html_text(translator, "bot.help.support_soon", locale))
    await message.answer("\n\n".join(parts), reply_markup=markup)


@inject
async def terms_command(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    telegram: FromDishka[TelegramSettings],
    versions: FromDishka[LegalVersions],
    library: FromDishka[LegalLibrary],
) -> None:
    await _legal(message, locale, LinkDocument.TERMS, translator, telegram, versions, library)


@inject
async def privacy_command(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    telegram: FromDishka[TelegramSettings],
    versions: FromDishka[LegalVersions],
    library: FromDishka[LegalLibrary],
) -> None:
    await _legal(message, locale, LinkDocument.PRIVACY, translator, telegram, versions, library)


@inject
async def fallback(message: Message, locale: Locale, translator: FromDishka[Translator]) -> None:
    await message.answer(html_text(translator, "bot.fallback", locale))


async def _legal(
    message: Message,
    locale: Locale,
    document: LinkDocument,
    translator: Translator,
    telegram: TelegramSettings,
    versions: LegalVersions,
    library: LegalLibrary,
) -> None:
    """Название, действующая редакция и кнопка на вкладку S48 (ссылка `l_<документ>`).

    Текст целиком в чат не шлём: правила длиннее лимита сообщения, а в Mini App — та же
    редакция, с которой человек соглашается.
    """
    title = plain_text(translator, f"bot.legal.{document}.title", locale)
    version = (await versions.legal_versions()).get(document.value)
    edition = library.edition(LegalDocument(document.value), version) if version else None
    if edition is None:
        text = html_text(translator, "bot.legal.text_no_version", locale, title=title)
    else:
        text = html_text(
            translator,
            "bot.legal.text",
            locale,
            title=title,
            version=edition.version,
            date=edition.published_on.strftime(DATE_FORMAT),
        )
    link = encode_start_param(StartLink(type=LinkType.LEGAL, document=document))
    markup = _open_app(translator, telegram, locale, f"bot.legal.{document}.open", link)
    await message.answer(text, reply_markup=markup)


def _open_app(
    translator: Translator,
    telegram: TelegramSettings,
    locale: Locale,
    label_key: str,
    start_param: str | None = None,
) -> InlineKeyboardMarkup | None:
    if not telegram.mini_app_url:
        return None
    label = plain_text(translator, label_key, locale)
    return open_app_keyboard(mini_app_url(telegram.mini_app_url, start_param), label)


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="bot-commands")
    private = F.chat.type == "private"
    router.message.register(app_command, Command("app"), private)
    router.message.register(help_command, Command("help"), private)
    router.message.register(terms_command, Command("terms"), private)
    router.message.register(privacy_command, Command("privacy"), private)
    router.message.register(fallback, private)  # последним: всё, что не взяли команды
    return router
