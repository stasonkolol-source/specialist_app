"""Многоязычный текст справочников (ADR-0013): ru, sr-Latn, sr-Cyrl, en.

Пользовательский контент (UGC) хранится на языке оригинала и сюда не относится.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.translit import sr_cyrl_to_latn


class Locale(StrEnum):
    RU = "ru"
    SR_LATN = "sr-Latn"
    SR_CYRL = "sr-Cyrl"
    EN = "en"


_FALLBACK: dict[Locale, tuple[Locale, ...]] = {
    Locale.RU: (Locale.RU, Locale.EN, Locale.SR_LATN, Locale.SR_CYRL),
    Locale.SR_LATN: (Locale.SR_LATN, Locale.SR_CYRL, Locale.EN, Locale.RU),
    Locale.SR_CYRL: (Locale.SR_CYRL, Locale.SR_LATN, Locale.EN, Locale.RU),
    Locale.EN: (Locale.EN, Locale.RU, Locale.SR_LATN, Locale.SR_CYRL),
}
"""Цепочки ARCHITECTURE §7.4. Для sr-Latn кириллица отдаётся транслитом, а не как есть."""


def fallback_chain(locale: Locale) -> tuple[Locale, ...]:
    return _FALLBACK[locale]


def as_requested(text: str, found: Locale, requested: Locale) -> str:
    """Текст локали `found` для запроса `requested`: sr-Cyrl для sr-Latn — транслитом."""
    if requested is Locale.SR_LATN and found is Locale.SR_CYRL:
        return sr_cyrl_to_latn(text)
    return text


@dataclass(frozen=True, slots=True)
class LocalizedText:
    values: Mapping[Locale, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cleaned = {Locale(k): v.strip() for k, v in self.values.items() if v and v.strip()}
        if not cleaned:
            raise DomainValidationError(field="localized_text", reason="empty")
        object.__setattr__(self, "values", MappingProxyType(cleaned))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, str]) -> LocalizedText:
        """Из JSONB: ключи — коды локалей. Неизвестная локаль — ошибка."""
        try:
            return cls({Locale(k): v for k, v in raw.items()})
        except ValueError as exc:
            raise DomainValidationError(field="localized_text", reason="unknown_locale") from exc

    def get(self, locale: Locale) -> str:
        """Текст на нужной локали или по цепочке запасных (§7.4)."""
        for candidate in _FALLBACK[locale]:
            if candidate in self.values:
                return as_requested(self.values[candidate], candidate, locale)
        return next(iter(self.values.values()))

    def with_sr_latn(self) -> LocalizedText:
        """sr-Latn из sr-Cyrl, если латиница не задана явно (§7.4: справочники при сохранении)."""
        if Locale.SR_LATN in self.values or Locale.SR_CYRL not in self.values:
            return self
        return LocalizedText(
            {**self.values, Locale.SR_LATN: sr_cyrl_to_latn(self.values[Locale.SR_CYRL])}
        )

    def to_mapping(self) -> dict[str, str]:
        return {k.value: v for k, v in self.values.items()}

    def __copy__(self) -> LocalizedText:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> LocalizedText:
        return self  # неизменяемый value object: копия не нужна
