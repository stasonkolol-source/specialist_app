"""Каталоги gettext в `backend/locales/<локаль>/LC_MESSAGES/messages.po` (ADR-0013).

- msgid — стабильный ключ (`errors.not_found`), а не фраза: правка русского текста не
  ломает сербский каталог. Параметры в тексте — `{name}`.
- ru и sr_Cyrl ведутся руками и полные; sr_Latn генерируется из sr_Cyrl транслитерацией
  (`cli i18n generate`), `cli i18n check` сверяет его с исходником; en — с v1.
- Каталоги читаются как .po при старте процесса: компиляция в .mo не нужна.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from babel.messages.pofile import read_po

from app.platform.kernel.localized import Locale
from app.platform.kernel.translit import sr_cyrl_to_latn

LOCALES_DIR = Path(__file__).resolve().parents[4] / "locales"
DOMAIN = "messages"
CATALOG_NAMES: Mapping[Locale, str] = {
    Locale.RU: "ru",
    Locale.SR_CYRL: "sr_Cyrl",
    Locale.SR_LATN: "sr_Latn",
    Locale.EN: "en",
}
COMPLETE = (Locale.RU, Locale.SR_CYRL)
"""Каталоги, в которых есть каждый ключ (сверяет архитектурный тест и `i18n check`)."""

_GENERATED_NOTE = "# СГЕНЕРИРОВАН из sr_Cyrl командой `cli i18n generate` — не править вручную.\n"


def catalog_path(locale: Locale, directory: Path = LOCALES_DIR) -> Path:
    return directory / CATALOG_NAMES[locale] / "LC_MESSAGES" / f"{DOMAIN}.po"


def read_catalog(path: Path) -> Mapping[str, str]:
    """msgid → msgstr без пустых и fuzzy-записей."""
    with path.open("rb") as file:
        catalog = read_po(file)
    return MappingProxyType(
        {
            str(message.id): str(message.string)
            for message in catalog
            if message.id and message.string and not message.fuzzy
        }
    )


def generate_sr_latn(source: str) -> str:
    """Текст sr_Latn из текста sr_Cyrl: транслит переводов (msgstr), ключи и комментарии как есть.

    В заголовке (запись с пустым msgid) меняется только `Language`.
    """
    lines = [_GENERATED_NOTE]
    msgid: str | None = None
    in_msgstr = False
    for line in source.splitlines(keepends=True):
        if line.startswith("msgid "):
            msgid, in_msgstr = line.removeprefix("msgid ").strip(), False
        elif line.startswith("msgstr "):
            in_msgstr = True
        elif not line.startswith('"'):
            in_msgstr = False
        if in_msgstr and msgid == '""':
            line = re.sub(r"Language: [^\\]+", "Language: sr_Latn", line)
        elif in_msgstr:
            line = sr_cyrl_to_latn(line)
        lines.append(line)
    return "".join(lines)


def stale_sr_latn(directory: Path = LOCALES_DIR) -> bool:
    source = catalog_path(Locale.SR_CYRL, directory).read_text(encoding="utf-8")
    target = catalog_path(Locale.SR_LATN, directory)
    return not target.exists() or target.read_text(encoding="utf-8") != generate_sr_latn(source)
