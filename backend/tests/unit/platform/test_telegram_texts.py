"""Тексты и кнопки бота (platform/telegram, DEVELOPMENT_PLAN 1.6)."""

import pytest
from pydantic import ValidationError

from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.texts import html_text, plain_text

pytestmark = pytest.mark.unit

BASE = "https://app.example/"


@pytest.mark.parametrize(
    ("base", "code", "expected"),
    [
        (BASE, None, BASE),
        (BASE, "h", f"{BASE}?startapp=h"),
        (
            BASE,
            "s_02yBkPi1NksSnHWzckDH0V_rAB12CD",
            f"{BASE}?startapp=s_02yBkPi1NksSnHWzckDH0V_rAB12CD",
        ),
        (BASE, "l_terms", f"{BASE}?startapp=l_terms"),
        (BASE, "not a link", BASE),
        (BASE, "_tgr_abc", BASE),
        (BASE, "x" * 65, BASE),
        (f"{BASE}?v=2", "h", f"{BASE}?v=2&startapp=h"),
        (f"{BASE}?startapp=old", "h", f"{BASE}?startapp=h"),
        (f"{BASE}#frag", "h", f"{BASE}?startapp=h#frag"),
    ],
    ids=[
        "no-code",
        "home",
        "with-ref",
        "legal",
        "text-after-start",
        "telegram-partner",
        "too-long",
        "keeps-query",
        "replaces-stale-code",
        "keeps-fragment",
    ],
)
def test_mini_app_url(base: str, code: str | None, expected: str) -> None:
    assert mini_app_url(base, code) == expected


def test_params_are_escaped_but_template_html_stays() -> None:
    translator = Translator({Locale.RU: {"k": "<b>{name}</b> — {name}"}})

    text = html_text(translator, "k", Locale.RU, name="<i>Ana</i> & Co")

    assert text == "<b>&lt;i&gt;Ana&lt;/i&gt; &amp; Co</b> — &lt;i&gt;Ana&lt;/i&gt; &amp; Co"


def test_missing_key_is_visible() -> None:
    translator = Translator({Locale.RU: {}})

    assert html_text(translator, "bot.nope", Locale.RU) == "bot.nope"
    assert plain_text(translator, "bot.nope", Locale.RU) == "bot.nope"


def _telegram(**values: str) -> TelegramSettings:
    return TelegramSettings(  # type: ignore[call-arg]
        _env_file=None,
        bot_token="1:x",  # noqa: S106 — фиктивный токен
        bot_username="b",
        **values,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@sosedi_support", "sosedi_support"),
        ("sosedi_support", "sosedi_support"),
        ("", None),
        ("  ", None),
    ],
)
def test_support_username_is_normalised(raw: str, expected: str | None) -> None:
    assert _telegram(support_username=raw).support_username == expected


@pytest.mark.parametrize("raw", ["ab", "https://t.me/x", "1support", "bad name"])
def test_support_username_rejects_non_usernames(raw: str) -> None:
    with pytest.raises(ValidationError):
        _telegram(support_username=raw)
