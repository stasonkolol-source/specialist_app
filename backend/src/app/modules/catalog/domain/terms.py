"""Словарь поиска `catalog.search_terms` (ARCHITECTURE §7.5, §9.3, ADR-0013).

Любой способ назвать потребность ведёт в категорию или тег: название на каждой локали и
синонимы из сидов. Ключ `norm` считает БД функцией platform.search_norm (нижний регистр,
кириллица → латиница, без диакритики, đ → dj), поэтому «електричар», «električar» и
«elektricar» дают один ключ. Здесь решается только, какие строки попадают в словарь,
с какой локалью и весом.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.localized import Locale, LocalizedText

NAME_WEIGHT: Final = 1.0
"""Официальное название выше синонима: автодополнение показывает его первым (§9.7)."""
SYNONYM_WEIGHT: Final = 0.8
MAX_TERM_LENGTH: Final = 120

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


class TermLanguage(StrEnum):
    """Язык синонима в сидах; сербский пишут и латиницей, и кириллицей."""

    RU = "ru"
    SR = "sr"
    EN = "en"


@dataclass(frozen=True, slots=True)
class SearchTerm:
    text: str
    locale: Locale
    weight: float = SYNONYM_WEIGHT

    def __post_init__(self) -> None:
        text = " ".join(self.text.split())
        if not text or len(text) > MAX_TERM_LENGTH:
            raise DomainValidationError(field="search_term", reason="length")
        object.__setattr__(self, "text", text)

    @classmethod
    def synonym(cls, text: str, language: TermLanguage) -> Self:
        """Синоним из сидов; у сербского локаль — по письменности строки."""
        return cls(text, term_locale(text, language))


def term_locale(text: str, language: TermLanguage) -> Locale:
    match language:
        case TermLanguage.RU:
            return Locale.RU
        case TermLanguage.EN:
            return Locale.EN
        case TermLanguage.SR:
            return Locale.SR_CYRL if _CYRILLIC.search(text) else Locale.SR_LATN


def dictionary(name: LocalizedText, synonyms: Iterable[SearchTerm] = ()) -> tuple[SearchTerm, ...]:
    """Строки словаря: название на каждой его локали (NAME_WEIGHT), затем синонимы.

    Повтор той же строки в той же локали без учёта регистра попадает один раз — с весом
    названия. sr-Latn названия генерирует вызывающий (`LocalizedText.with_sr_latn`).
    """
    names = (SearchTerm(text, locale, NAME_WEIGHT) for locale, text in name.values.items())
    seen: set[tuple[Locale, str]] = set()
    terms: list[SearchTerm] = []
    for term in (*names, *synonyms):
        key = (term.locale, term.text.casefold())
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return tuple(terms)
