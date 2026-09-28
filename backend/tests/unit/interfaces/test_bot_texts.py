"""Тексты бота — валидный HTML Bot API на всех языках (DEVELOPMENT_PLAN 1.6).

Битый тег или голый `&`/`<` в каталоге Telegram не показывает, а отвергает сообщение целиком
(«can't parse entities») — для всех людей этого языка. Проверяем каждый шаблон `bot.*`,
который уходит как HTML, после подстановки параметров.
"""

import re
from html.parser import HTMLParser
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from app.modules.identity.bot.handlers import _edit_once
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit

TELEGRAM_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
     "tg-spoiler", "span", "blockquote", "tg-emoji"}
)  # fmt: skip
PLAIN = re.compile(r"bot\.(profile|commands)\.|\.(open|title)$|support_button$")
"""Имя, описания и меню команд, подписи кнопок — текст без разметки (Telegram не парсит)."""
LOCALES = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN)
BAD_AMPERSAND = re.compile(r"&(?!(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);)")


class TelegramHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in TELEGRAM_TAGS:
            self.problems.append(f"tag <{tag}> is not supported by Telegram")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.problems.append(f"unbalanced </{tag}>")


def problems(text: str) -> list[str]:
    parser = TelegramHtml()
    parser.feed(text)
    parser.close()
    found = parser.problems + [f"unclosed <{tag}>" for tag in parser.stack]
    if BAD_AMPERSAND.search(text):
        found.append("bare & (use &amp;)")
    if re.search(r"<(?![a-z/])", text):
        found.append("bare < (use &lt;)")
    return found


@pytest.fixture(scope="module")
def translator() -> Translator:
    return Translator.load()


@pytest.mark.parametrize("locale", LOCALES, ids=str)
def test_every_html_bot_text_is_valid_telegram_html(translator: Translator, locale: Locale) -> None:
    keys = sorted(
        k for k in translator.keys(locale) if k.startswith("bot.") and not PLAIN.search(k)
    )
    assert len(keys) >= 12  # тексты команд 1.6 на месте

    broken = {}
    for key in keys:
        template = translator.text(key, locale) or ""
        params = dict.fromkeys(re.findall(r"{(\w+)}", template), "X")
        if found := problems(translator.text(key, locale, **params) or ""):
            broken[key] = found
    assert broken == {}


def test_validator_catches_what_telegram_rejects() -> None:
    assert problems("<b>ok</b> &amp; &lt;") == []
    assert problems("<b>open") == ["unclosed <b>"]
    assert problems("<p>para</p>") == ["tag <p> is not supported by Telegram"]
    assert problems("Q&A") == ["bare & (use &amp;)"]
    assert problems("1 < 2") == ["bare < (use &lt;)"]


def _not_modified(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=EditMessageText(text="x"), message=text)


async def test_double_tap_edit_is_not_an_error() -> None:
    message = AsyncMock()
    message.edit_text.side_effect = _not_modified(
        "Bad Request: message is not modified: specified new message content and reply markup"
        " are exactly the same"
    )

    await _edit_once(message, "Готово")  # второе нажатие — без исключения и без Sentry


async def test_other_edit_errors_are_raised() -> None:
    message = AsyncMock()
    message.edit_text.side_effect = _not_modified("Bad Request: message can't be edited")

    with pytest.raises(TelegramBadRequest):
        await _edit_once(message, "Готово")
