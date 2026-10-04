"""Профиль бота для `cli bot-setup` (DEVELOPMENT_PLAN 1.6): тексты в лимитах Bot API и
идемпотентное применение — повторный запуск ничего не меняет; меню команд — по областям
(личные чаты и администраторы групп)."""

from dataclasses import dataclass, field
from typing import Any

import pytest
from aiogram.types import BotCommand, MenuButtonWebApp

from app.interfaces.bot.profile import (
    COMMANDS,
    GROUP_ADMIN_COMMANDS,
    BotProfile,
    apply_menu_button,
    apply_profile,
    bot_profiles,
)
from app.platform.i18n.translator import Translator
from app.platform.settings import Environment

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def translator() -> Translator:
    return Translator.load()


@pytest.mark.parametrize("env", list(Environment))
def test_profiles_fit_bot_api_limits(translator: Translator, env: Environment) -> None:
    profiles = bot_profiles(translator, env)

    assert [p.language_code for p in profiles] == [None, "ru", "sr"]
    assert [problem for p in profiles for problem in p.problems()] == []
    for profile in profiles:
        assert [c.command for c in profile.commands] == list(COMMANDS)
        assert [c.command for c in profile.group_commands] == list(GROUP_ADMIN_COMMANDS)
        commands = (*profile.commands, *profile.group_commands)
        assert not any(c.description.startswith("bot.") for c in commands)


def test_name_shows_environment_outside_production(translator: Translator) -> None:
    names = {
        env: [p.name for p in bot_profiles(translator, env)]
        for env in (Environment.DEV, Environment.PRODUCTION)
    }

    assert names[Environment.DEV] == ["Соседи dev", "Соседи dev", "Sosedi dev"]
    assert names[Environment.PRODUCTION] == ["Соседи", "Соседи", "Sosedi"]


def test_serbian_profile_is_latin(translator: Translator) -> None:
    sr = bot_profiles(translator, Environment.PRODUCTION)[2]

    assert sr.short_description.startswith("Majstori i pomoć u blizini")
    assert sr.commands[0].description == "Otvori aplikaciju"


def test_problems_name_the_broken_limit() -> None:
    profile = BotProfile(
        language_code="ru",
        name="x" * 65,
        description="d",
        short_description="s" * 121,
        commands=(BotCommand(command="app", description="x" * 257),),
    )

    assert profile.problems() == [
        "ru: name is 65 chars (1..64)",
        "ru: short description is 121 chars",
        "ru: /app description is 257 chars",
    ]


@dataclass
class Value:
    name: str = ""
    description: str = ""
    short_description: str = ""


@dataclass
class FakeBot:
    """Профиль бота в Telegram: get_* отдают сохранённое, set_* сохраняют и считаются; команды —
    по области (`scope.type`) и языку."""

    names: dict[str | None, str] = field(default_factory=dict)
    descriptions: dict[str | None, str] = field(default_factory=dict)
    shorts: dict[str | None, str] = field(default_factory=dict)
    commands: dict[tuple[str, str | None], list[BotCommand]] = field(default_factory=dict)
    menu: Any = None
    sets: list[str] = field(default_factory=list)

    async def get_my_name(self, language_code: str | None = None) -> Value:
        return Value(name=self.names.get(language_code, ""))

    async def set_my_name(self, name: str, language_code: str | None = None) -> None:
        self.names[language_code] = name
        self.sets.append(f"name:{language_code}")

    async def get_my_description(self, language_code: str | None = None) -> Value:
        return Value(description=self.descriptions.get(language_code, ""))

    async def set_my_description(self, description: str, language_code: str | None = None) -> None:
        self.descriptions[language_code] = description
        self.sets.append(f"description:{language_code}")

    async def get_my_short_description(self, language_code: str | None = None) -> Value:
        return Value(short_description=self.shorts.get(language_code, ""))

    async def set_my_short_description(
        self, short_description: str, language_code: str | None = None
    ) -> None:
        self.shorts[language_code] = short_description
        self.sets.append(f"short:{language_code}")

    async def get_my_commands(
        self, scope: Any, language_code: str | None = None
    ) -> list[BotCommand]:
        return list(self.commands.get((scope.type, language_code), []))

    async def set_my_commands(
        self, commands: list[BotCommand], scope: Any, language_code: str | None = None
    ) -> None:
        self.commands[scope.type, language_code] = commands
        self.sets.append(f"commands:{scope.type}:{language_code}")

    async def get_chat_menu_button(self) -> Any:
        return self.menu

    async def set_chat_menu_button(self, menu_button: Any) -> None:
        self.menu = menu_button
        self.sets.append("menu")


async def test_second_run_changes_nothing(translator: Translator) -> None:
    bot: Any = FakeBot()
    profiles = bot_profiles(translator, Environment.DEV)

    first = [await apply_profile(bot, p) for p in profiles]
    calls_after_first = len(bot.sets)
    second = [await apply_profile(bot, p) for p in profiles]

    assert first == [["name", "description", "short description", "commands", "group commands"]] * 3
    assert second == [[], [], []]
    assert len(bot.sets) == calls_after_first == 15


async def test_chatid_is_only_in_the_group_admins_menu(translator: Translator) -> None:
    """Команды клиента — в личных чатах; у администраторов групп — только `/chatid` (K29)."""
    bot: Any = FakeBot()
    for profile in bot_profiles(translator, Environment.DEV):
        await apply_profile(bot, profile)

    private = [c.command for c in bot.commands["all_private_chats", "ru"]]
    admins = bot.commands["all_chat_administrators", "ru"]
    assert private == list(COMMANDS)
    assert "chatid" not in private
    assert [(c.command, c.description) for c in admins] == [
        ("chatid", "Id этого чата — для персонала")
    ]
    assert bot.commands["all_chat_administrators", "sr"][0].description == (
        "ID ove grupe — za osoblje"
    )


async def test_only_changed_fields_are_set(translator: Translator) -> None:
    bot: Any = FakeBot()
    profile = bot_profiles(translator, Environment.DEV)[1]
    await apply_profile(bot, profile)
    bot.descriptions["ru"] = "старое описание"
    bot.sets.clear()

    assert await apply_profile(bot, profile) == ["description"]
    assert bot.sets == ["description:ru"]


async def test_menu_button_is_set_once() -> None:
    bot: Any = FakeBot()

    assert await apply_menu_button(bot, "https://app.example/", "Открыть") is True
    assert await apply_menu_button(bot, "https://app.example/", "Открыть") is False
    assert await apply_menu_button(bot, "https://new.example/", "Открыть") is True
    assert isinstance(bot.menu, MenuButtonWebApp)
    assert bot.menu.web_app.url == "https://new.example/"


async def test_menu_button_matches_telegram_normalised_url() -> None:
    """Telegram отдаёт адрес с `/` на конце голого хоста: это тот же адрес, не повод менять."""
    bot: Any = FakeBot()
    await apply_menu_button(bot, "https://app.example/", "Открыть")

    assert await apply_menu_button(bot, "https://app.example", "Открыть") is False
    assert await apply_menu_button(bot, "https://APP.example/", "Открыть") is False
    assert await apply_menu_button(bot, "https://app.example/other", "Открыть") is True
