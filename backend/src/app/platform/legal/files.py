"""Тексты правовых документов из файлов `backend/content/legal` (DEVELOPMENT_PLAN 1.5a).

Раскладка: `<документ>/<версия>/<язык>.md`, например `terms/draft-1/ru.md`. Языки файлов —
ru и sr-Cyrl, sr-Latn получается транслитерацией sr-Cyrl (как каталоги, ADR-0013).

Файл:

- начинается с front matter YAML с датой редакции (`date: 2026-09-27`);
- HTML-комментарии `<!-- … -->` — заметки для владельца, клиент их не получает;
- первая строка текста — заголовок `# …`, он уходит в `title`, остальное — Markdown в `body`;
- `{{appName}}`, `{{OPERATOR_NAME}}`, `{{CONTACT_EMAIL}}` подставляются из настроек.
  Неизвестная подстановка — ошибка загрузки, а не «{{…}}» в тексте у пользователя.

Все файлы читаются и проверяются один раз, при создании объекта (Scope.APP): ошибка в
тексте роняет старт процесса и тест `test_legal`, а не всплывает у пользователя.
"""

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Final

import yaml

from app.platform.kernel.localized import Locale
from app.platform.kernel.translit import sr_cyrl_to_latn
from app.platform.legal.port import LegalDocument, LegalEdition, LegalLibrary, LegalText
from app.platform.settings import AppSettings, LegalSettings

LEGAL_DIR: Final = Path(__file__).resolve().parents[4] / "content" / "legal"
SOURCE_LOCALES: Final = (Locale.RU, Locale.SR_CYRL)
"""Языки файлов. ru — обязателен в каждой версии: это исходник, от него переводят."""

_VERSION = re.compile(r"[a-z0-9][a-z0-9.-]{0,31}")
_FRONT_MATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_BLANK_LINES = re.compile(r"\n{3,}")


def placeholders(app: AppSettings, legal: LegalSettings) -> dict[str, str]:
    """Подстановки документов из настроек: имя продукта, оператор данных, почта поддержки."""
    return {
        "appName": app.name,
        "OPERATOR_NAME": legal.operator_name,
        "CONTACT_EMAIL": legal.contact_email,
    }


class LegalContentError(ValueError):
    """Файл документа не по правилам: процесс не должен отдавать такой текст."""


class FileLegalLibrary(LegalLibrary):
    def __init__(self, placeholders: Mapping[str, str], directory: Path = LEGAL_DIR) -> None:
        editions: dict[tuple[LegalDocument, str], LegalEdition] = {}
        for document in LegalDocument:
            for folder in sorted(p for p in (directory / document).glob("*") if p.is_dir()):
                editions[document, folder.name] = _edition(document, folder, placeholders)
        self._editions = MappingProxyType(editions)

    def edition(self, document: LegalDocument, version: str) -> LegalEdition | None:
        return self._editions.get((document, version))

    def versions(self, document: LegalDocument) -> frozenset[str]:
        return frozenset(version for doc, version in self._editions if doc is document)


def _edition(
    document: LegalDocument, folder: Path, placeholders: Mapping[str, str]
) -> LegalEdition:
    if not _VERSION.fullmatch(folder.name):
        raise LegalContentError(f"{folder}: версия — строчные латиница, цифры, «.» и «-»")
    known = {f"{locale.value}.md" for locale in SOURCE_LOCALES}
    files = [p.name for p in folder.iterdir() if not p.name.startswith(".")]
    unknown = sorted(name for name in files if name not in known)
    if unknown:
        raise LegalContentError(f"{folder}: лишние файлы {unknown}; языки — {sorted(known)}")
    parsed = {
        locale: _parse(folder / f"{locale.value}.md", placeholders)
        for locale in SOURCE_LOCALES
        if (folder / f"{locale.value}.md").exists()
    }
    if Locale.RU not in parsed:
        raise LegalContentError(f"{folder}: нет ru.md — исходника версии")
    dates = {published_on for published_on, _ in parsed.values()}
    if len(dates) > 1:
        raise LegalContentError(f"{folder}: у переводов одной версии разные даты редакции")
    texts = {locale: text for locale, (_, text) in parsed.items()}
    if (cyrillic := texts.get(Locale.SR_CYRL)) is not None:
        texts[Locale.SR_LATN] = LegalText(
            title=sr_cyrl_to_latn(cyrillic.title), body=sr_cyrl_to_latn(cyrillic.body)
        )
    return LegalEdition(
        document=document,
        version=folder.name,
        published_on=dates.pop(),
        texts=MappingProxyType(texts),
    )


def _parse(path: Path, placeholders: Mapping[str, str]) -> tuple[date, LegalText]:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONT_MATTER.match(raw)
    if match is None:
        raise LegalContentError(f"{path}: нет front matter с датой редакции (---\\ndate: …\\n---)")
    meta = yaml.safe_load(match["meta"])
    published_on = meta.get("date") if isinstance(meta, dict) else None
    if not isinstance(published_on, date):
        raise LegalContentError(f"{path}: в front matter нет даты `date: ГГГГ-ММ-ДД`")
    text = _substitute(_COMMENT.sub("", raw[match.end() :]), placeholders, path).strip()
    heading, _, body = text.partition("\n")
    if not heading.startswith("# "):
        raise LegalContentError(f"{path}: текст начинается не с заголовка «# …»")
    return published_on, LegalText(
        title=heading.removeprefix("# ").strip(),
        body=_BLANK_LINES.sub("\n\n", body).strip() + "\n",
    )


def _substitute(text: str, placeholders: Mapping[str, str], path: Path) -> str:
    unknown = sorted({m["name"] for m in _PLACEHOLDER.finditer(text)} - placeholders.keys())
    if unknown:
        raise LegalContentError(f"{path}: неизвестные подстановки {unknown}")
    return _PLACEHOLDER.sub(lambda m: placeholders[m["name"]], text)
