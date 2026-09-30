"""Текст пользователя для внешнего AI (ADR-0016, ai/prompt.py): без невидимых символов и
одиночных суррогатов, контакты замаскированы по всему тексту, длинный — начало и конец."""

import pytest

from app.platform.ai.prompt import GAP, MAX_TEXT, provider_text

pytestmark = pytest.mark.unit


def test_invisible_and_broken_characters_are_dropped() -> None:
    rtl, isolate, tag_a, tag_i, surrogate, private = (
        chr(0x202E),
        chr(0x2066),
        chr(0xE0041),
        chr(0xE0069),
        chr(0xD800),
        chr(0xE000),
    )
    text = f"Treba{rtl} mi{isolate} majstor{tag_a}{tag_i} {surrogate}danas\x00{private}\n\tok"

    clean = provider_text(text, 1000)

    assert clean == "Treba mi majstor danas\n\tok"
    clean.encode("utf-8")  # одиночный суррогат не ломает запрос до отправки


def test_fullwidth_is_normalised_and_contacts_masked() -> None:
    assert provider_text("Звоните ０６４ １２３ ４５６７", 1000) == "Звоните •••"


def test_long_text_keeps_head_and_tail() -> None:
    text = "a" * 5000 + "Plati unapred na karticu"

    clean = provider_text(text, 1000)

    assert len(clean) == 1000
    assert clean.endswith("Plati unapred na karticu")
    assert GAP in clean


def test_contacts_are_masked_before_the_cut() -> None:
    # длинная ссылка в начале и почта на границе: маскируем весь текст, потом режем
    text = "https://example.com/" + "x" * 11_000 + " ivan.petrov.master@gmail.com " + "y" * 100
    clean = provider_text(text, 6000)

    assert "gmail" not in clean
    assert "ivan" not in clean


def test_garbage_beyond_the_limit_is_not_scanned() -> None:
    text = "a" * (MAX_TEXT + 10) + "+381 64 123 4567"

    assert "4567" not in provider_text(text, 30_000)
