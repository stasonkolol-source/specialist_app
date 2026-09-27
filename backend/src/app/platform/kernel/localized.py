"""Многоязычный текст справочников (ADR-0013): ru, sr-Latn, sr-Cyrl, en.

Пользовательский контент (UGC) хранится на языке оригинала и сюда не относится.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from app.platform.kernel.errors import DomainValidationError


class Locale(StrEnum):
    RU = "ru"
    SR_LATN = "sr-Latn"
    SR_CYRL = "sr-Cyrl"
    EN = "en"


_FALLBACK: dict[Locale, tuple[Locale, ...]] = {
    Locale.RU: (Locale.RU, Locale.SR_LATN, Locale.EN, Locale.SR_CYRL),
    Locale.SR_LATN: (Locale.SR_LATN, Locale.SR_CYRL, Locale.EN, Locale.RU),
    Locale.SR_CYRL: (Locale.SR_CYRL, Locale.SR_LATN, Locale.EN, Locale.RU),
    Locale.EN: (Locale.EN, Locale.RU, Locale.SR_LATN, Locale.SR_CYRL),
}


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
        """Текст на нужной локали или по цепочке запасных: сербские варианты — друг к другу."""
        for candidate in _FALLBACK[locale]:
            if candidate in self.values:
                return self.values[candidate]
        return next(iter(self.values.values()))

    def to_mapping(self) -> dict[str, str]:
        return {k.value: v for k, v in self.values.items()}
