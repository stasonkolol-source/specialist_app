"""Тексты на языке получателя (ADR-0013): ключ → текст по цепочке fallback §7.4.

Один объект на процесс: каталоги загружаются при сборке контейнера (entrypoints) и
приходят через DI; HTTP берёт отсюда `detail` ошибок, бот и уведомления — свои тексты.
"""

from collections.abc import Mapping
from pathlib import Path

from app.platform.i18n.catalogs import CATALOG_NAMES, LOCALES_DIR, catalog_path, read_catalog
from app.platform.kernel.localized import Locale, fallback_chain


class _KeepMissing(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Translator:
    def __init__(self, catalogs: Mapping[Locale, Mapping[str, str]]) -> None:
        self._catalogs = catalogs

    @classmethod
    def load(cls, directory: Path = LOCALES_DIR) -> Translator:
        catalogs = {
            locale: read_catalog(catalog_path(locale, directory))
            for locale in CATALOG_NAMES
            if catalog_path(locale, directory).exists()
        }
        return cls(catalogs)

    def text(self, key: str, locale: Locale, **params: object) -> str | None:
        """Текст ключа на локали или по цепочке; None — ключа нет ни в одном каталоге."""
        for candidate in fallback_chain(locale):
            template = self._catalogs.get(candidate, {}).get(key)
            if template:
                return template.format_map(_KeepMissing(params))
        return None

    def keys(self, locale: Locale) -> frozenset[str]:
        return frozenset(self._catalogs.get(locale, {}))
