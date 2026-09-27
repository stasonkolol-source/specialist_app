"""Словарь поиска: локаль по письменности, названия выше синонимов, без повторов (§7.5)."""

import pytest

from app.modules.catalog.domain.terms import (
    MAX_TERM_LENGTH,
    NAME_WEIGHT,
    SYNONYM_WEIGHT,
    SearchTerm,
    TermLanguage,
    dictionary,
    term_locale,
)
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.localized import Locale, LocalizedText

pytestmark = pytest.mark.unit

ELECTRICIAN = LocalizedText(
    {
        Locale.RU: "Электрик",
        Locale.SR_CYRL: "Електричар",
        Locale.SR_LATN: "Električar",
        Locale.EN: "Electrician",
    }
)


@pytest.mark.parametrize(
    ("text", "language", "locale"),
    [
        ("электрик", TermLanguage.RU, Locale.RU),
        ("električar", TermLanguage.SR, Locale.SR_LATN),
        ("elektricar", TermLanguage.SR, Locale.SR_LATN),
        ("струја", TermLanguage.SR, Locale.SR_CYRL),
        ("Љубав", TermLanguage.SR, Locale.SR_CYRL),
        ("montaža ikea", TermLanguage.SR, Locale.SR_LATN),
        ("electrician", TermLanguage.EN, Locale.EN),
    ],
)
def test_serbian_locale_follows_the_script(
    text: str, language: TermLanguage, locale: Locale
) -> None:
    assert term_locale(text, language) is locale
    assert SearchTerm.synonym(text, language).locale is locale


def test_term_text_is_trimmed_and_bounded() -> None:
    assert SearchTerm("  повесить   люстру ", Locale.RU).text == "повесить люстру"
    for bad in ("", "   ", "x" * (MAX_TERM_LENGTH + 1)):
        with pytest.raises(DomainValidationError):
            SearchTerm(bad, Locale.RU)


def test_dictionary_puts_names_first_then_synonyms() -> None:
    terms = dictionary(
        ELECTRICIAN,
        [
            SearchTerm.synonym("розетка", TermLanguage.RU),
            SearchTerm.synonym("струја", TermLanguage.SR),
        ],
    )
    assert [(t.locale, t.text, t.weight) for t in terms] == [
        (Locale.RU, "Электрик", NAME_WEIGHT),
        (Locale.SR_CYRL, "Електричар", NAME_WEIGHT),
        (Locale.SR_LATN, "Električar", NAME_WEIGHT),
        (Locale.EN, "Electrician", NAME_WEIGHT),
        (Locale.RU, "розетка", SYNONYM_WEIGHT),
        (Locale.SR_CYRL, "струја", SYNONYM_WEIGHT),
    ]


def test_dictionary_drops_repeats_ignoring_case_but_keeps_other_locales() -> None:
    terms = dictionary(
        ELECTRICIAN,
        [
            SearchTerm.synonym("электрик", TermLanguage.RU),  # = название ru
            SearchTerm.synonym("ELEKTRIČAR", TermLanguage.SR),  # = название sr-Latn
            SearchTerm.synonym("электрик", TermLanguage.EN),  # другая локаль — остаётся
            SearchTerm.synonym("utičnica", TermLanguage.SR),
            SearchTerm.synonym("Utičnica", TermLanguage.SR),
        ],
    )
    synonyms = [(t.locale, t.text) for t in terms if t.weight == SYNONYM_WEIGHT]
    assert synonyms == [(Locale.EN, "электрик"), (Locale.SR_LATN, "utičnica")]
    assert len(terms) == 6


def test_dictionary_of_a_name_alone() -> None:
    tag = LocalizedText({Locale.RU: "IKEA", Locale.SR_CYRL: "IKEA"})
    assert [(t.locale, t.text) for t in dictionary(tag)] == [
        (Locale.RU, "IKEA"),
        (Locale.SR_CYRL, "IKEA"),
    ]
