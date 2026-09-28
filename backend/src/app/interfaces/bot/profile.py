"""Профиль бота в Telegram (DEVELOPMENT_PLAN 1.6): имя, описания и меню команд на ru и sr.

`cli bot-setup --env <env>` сверяет профиль с тем, что уже стоит у бота, и меняет только
отличия: у setMyName и setMyDescription жёсткие лимиты частоты, повторный запуск не должен
упираться во flood wait. Языки профиля: по умолчанию и `ru` — русский; `sr` — sr-Latn, как
бот отвечает клиентам с language_code `sr` (interfaces/bot/middlewares.py). Имя вне прода
получает окружение: «Соседи dev», «Соседи stage».
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonWebApp, WebAppInfo

from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.settings import Environment
from app.platform.telegram.texts import plain_text

PROFILE_LANGUAGES: Final[Mapping[str | None, Locale]] = {
    None: Locale.RU,
    "ru": Locale.RU,
    "sr": Locale.SR_LATN,
}
"""language_code Bot API → локаль текстов; None — профиль по умолчанию (любой другой язык)."""
COMMANDS: Final = ("app", "help", "terms", "privacy", "language")
"""Меню команд по порядку. /start Telegram показывает сам; остальные — в своих шагах."""

NAME_LIMIT: Final = 64
DESCRIPTION_LIMIT: Final = 512
SHORT_DESCRIPTION_LIMIT: Final = 120
COMMAND_DESCRIPTION_LIMITS: Final = (1, 256)


@dataclass(frozen=True, slots=True, kw_only=True)
class BotProfile:
    language_code: str | None
    name: str
    description: str
    short_description: str
    commands: tuple[BotCommand, ...]

    def problems(self) -> list[str]:
        """Нарушения лимитов Bot API — до вызова, чтобы не получить 400 на полпути."""
        where = self.language_code or "default"
        found = []
        if not 0 < len(self.name) <= NAME_LIMIT:
            found.append(f"{where}: name is {len(self.name)} chars (1..{NAME_LIMIT})")
        if len(self.description) > DESCRIPTION_LIMIT:
            found.append(f"{where}: description is {len(self.description)} chars")
        if len(self.short_description) > SHORT_DESCRIPTION_LIMIT:
            found.append(f"{where}: short description is {len(self.short_description)} chars")
        low, high = COMMAND_DESCRIPTION_LIMITS
        found += [
            f"{where}: /{c.command} description is {len(c.description)} chars"
            for c in self.commands
            if not low <= len(c.description) <= high
        ]
        return found


def bot_profiles(translator: Translator, env: Environment) -> list[BotProfile]:
    suffix = "" if env is Environment.PRODUCTION else f" {env.value}"
    return [
        BotProfile(
            language_code=code,
            name=plain_text(translator, "bot.profile.name", locale) + suffix,
            description=plain_text(translator, "bot.profile.description", locale),
            short_description=plain_text(translator, "bot.profile.short_description", locale),
            commands=tuple(
                BotCommand(
                    command=name,
                    description=plain_text(translator, f"bot.commands.{name}", locale),
                )
                for name in COMMANDS
            ),
        )
        for code, locale in PROFILE_LANGUAGES.items()
    ]


async def apply_profile(bot: Bot, profile: BotProfile) -> list[str]:
    """Выставить профиль одного языка; вернуть имена изменённых полей (пусто — всё совпало)."""
    lang = profile.language_code
    changed: list[str] = []
    if (await bot.get_my_name(language_code=lang)).name != profile.name:
        await bot.set_my_name(name=profile.name, language_code=lang)
        changed.append("name")
    current = await bot.get_my_description(language_code=lang)
    if current.description != profile.description:
        await bot.set_my_description(description=profile.description, language_code=lang)
        changed.append("description")
    short = await bot.get_my_short_description(language_code=lang)
    if short.short_description != profile.short_description:
        await bot.set_my_short_description(
            short_description=profile.short_description, language_code=lang
        )
        changed.append("short description")
    # только личные чаты: в группах (чат модераторов, чат дома) команды бота не работают
    scope = BotCommandScopeAllPrivateChats()
    commands = await bot.get_my_commands(scope=scope, language_code=lang)
    if _pairs(commands) != _pairs(profile.commands):
        await bot.set_my_commands(list(profile.commands), scope=scope, language_code=lang)
        changed.append("commands")
    return changed


async def apply_menu_button(bot: Bot, url: str, label: str) -> bool:
    """Кнопка меню открывает Mini App; True — поменяли."""
    current = await bot.get_chat_menu_button()
    if (
        isinstance(current, MenuButtonWebApp)
        and current.text == label
        and _same_url(current.web_app.url, url)
    ):
        return False
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text=label, web_app=WebAppInfo(url=url))
    )
    return True


def _same_url(a: str, b: str) -> bool:
    """Telegram хранит адрес нормализованным: к голому хосту дописывает `/`."""
    return _normalized(a) == _normalized(b)


def _normalized(url: str) -> tuple[str, str, str, str, str]:
    parts = urlsplit(url)
    return (parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, parts.fragment)


def _pairs(commands: Sequence[BotCommand]) -> list[tuple[str, str]]:
    return [(c.command, c.description) for c in commands]
