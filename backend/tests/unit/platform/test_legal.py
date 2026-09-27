"""Тексты правовых документов (DEVELOPMENT_PLAN 1.5a): файлы репозитория и правила разбора."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.platform.kernel.localized import Locale
from app.platform.legal.files import LEGAL_DIR, FileLegalLibrary, LegalContentError
from app.platform.legal.port import LegalDocument
from app.platform.testing.config import DRAFT_LEGAL_VERSIONS

pytestmark = pytest.mark.unit

PLACEHOLDERS = {
    "appName": "Сосед",
    "OPERATOR_NAME": "ООО «Тест»",
    "CONTACT_EMAIL": "help@example.test",
}
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture(scope="module")
def library() -> FileLegalLibrary:
    return FileLegalLibrary(PLACEHOLDERS)


def test_every_document_is_published(library: FileLegalLibrary) -> None:
    for document in LegalDocument:
        assert library.versions(document), document
    result = CliRunner().invoke(cli.app, ["legal-validate"])
    assert result.exit_code == 0, result.output
    assert "legal: OK" in result.output


def test_versions_seeded_by_migrations_have_texts(library: FileLegalLibrary) -> None:
    """client-config из миграций указывает на опубликованные тексты: иначе S48 пуст."""
    seeded = "".join(p.read_text(encoding="utf-8") for p in MIGRATIONS.glob("platform_*.py"))
    for document, version in DRAFT_LEGAL_VERSIONS.items():
        assert f'"{document}": "{version}"' in seeded, document
        assert version in library.versions(LegalDocument(document))


@pytest.mark.parametrize("document", list(LegalDocument))
def test_repository_texts_are_clean(library: FileLegalLibrary, document: LegalDocument) -> None:
    for version in library.versions(document):
        edition = library.edition(document, version)
        assert edition is not None
        assert (edition.document, edition.version) == (document, version)
        assert isinstance(edition.published_on, date)
        text = edition.texts[Locale.RU]
        assert text.title.startswith(("Правила", "Политика"))
        assert "Сосед" in text.title
        assert not text.body.startswith("#")
        for leftover in ("{{", "}}", "<!--", "-->", "Решение владельца", "\n\n\n"):
            assert leftover not in text.body, leftover
    privacy = library.edition(LegalDocument.PRIVACY, "draft-1")
    assert privacy is not None
    assert "help@example.test" in privacy.texts[Locale.RU].body


def test_drafts_have_only_russian_until_translated(library: FileLegalLibrary) -> None:
    """Сербский перевод — после правок владельца (K22) и вычитки носителем (K41)."""
    for document in LegalDocument:
        edition = library.edition(document, "draft-1")
        assert edition is not None
        assert set(edition.texts) == {Locale.RU}


def test_unknown_version_is_none(library: FileLegalLibrary) -> None:
    assert library.edition(LegalDocument.TERMS, "draft-0") is None


# --- правила разбора на временных файлах ---------------------------------------------------

SAMPLE = """---
date: 2026-10-01
---
<!-- заметка для владельца,
     на несколько строк -->

# Правила {{appName}}

Текст для {{ appName }}.
<!-- Решение владельца: скрыть -->


## 1. Раздел
"""


def _write(root: Path, relative: str, content: str = SAMPLE) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_sample_is_parsed_into_title_date_and_body(tmp_path: Path) -> None:
    _write(tmp_path, "terms/v2/ru.md")
    edition = FileLegalLibrary(PLACEHOLDERS, tmp_path).edition(LegalDocument.TERMS, "v2")
    assert edition is not None
    assert edition.published_on == date(2026, 10, 1)
    assert list(edition.texts) == [Locale.RU]
    assert edition.texts[Locale.RU].title == "Правила Сосед"
    assert edition.texts[Locale.RU].body == "Текст для Сосед.\n\n## 1. Раздел\n"


def test_serbian_latin_is_transliterated_from_cyrillic(tmp_path: Path) -> None:
    _write(tmp_path, "terms/v2/ru.md")
    serbian = (
        SAMPLE.replace("Правила", "Љубазна правила")
        .replace("Текст для", "Текст за")
        .replace("Раздел", "Одељак")
    )
    _write(tmp_path, "terms/v2/sr-Cyrl.md", serbian)
    edition = FileLegalLibrary(PLACEHOLDERS, tmp_path).edition(LegalDocument.TERMS, "v2")
    assert edition is not None
    assert set(edition.texts) == {Locale.RU, Locale.SR_CYRL, Locale.SR_LATN}
    assert edition.texts[Locale.SR_CYRL].title == "Љубазна правила Сосед"
    assert edition.texts[Locale.SR_LATN].title == "Ljubazna pravila Sosed"
    assert edition.texts[Locale.SR_LATN].body == "Tekst za Sosed.\n\n## 1. Odeljak\n"


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"terms/v2/ru.md": SAMPLE.replace("date: 2026-10-01\n", "")}, "дат"),
        (
            {"terms/v2/ru.md": SAMPLE.replace("date: 2026-10-01", "date: 2026-10-01 09:00:00")},
            "дат",
        ),
        ({"terms/v2/ru.md": SAMPLE.split("---\n", 2)[2]}, "front matter"),
        ({"terms/v2/ru.md": SAMPLE.replace("{{appName}}", "{{APP}}")}, "APP"),
        ({"terms/v2/ru.md": SAMPLE.replace("# Правила", "Правила")}, "заголовк"),
        ({"terms/v2/sr-Cyrl.md": SAMPLE}, "ru.md"),
        ({"terms/v2/ru.md": SAMPLE, "terms/v2/sr-Latn.md": SAMPLE}, "sr-Latn"),
        ({"terms/V2/ru.md": SAMPLE}, "версия"),
        (
            {
                "terms/v2/ru.md": SAMPLE,
                "terms/v2/sr-Cyrl.md": SAMPLE.replace("2026-10-01", "2026-10-02"),
            },
            "дат",
        ),
    ],
)
def test_broken_files_fail_loading(tmp_path: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        _write(tmp_path, relative, content)
    with pytest.raises(LegalContentError, match=message):
        FileLegalLibrary(PLACEHOLDERS, tmp_path)


def test_hidden_files_are_ignored(tmp_path: Path) -> None:
    shutil.copytree(LEGAL_DIR, tmp_path / "legal")
    _write(tmp_path, "legal/terms/draft-1/.DS_Store", "")
    assert FileLegalLibrary(PLACEHOLDERS, tmp_path / "legal").versions(LegalDocument.TERMS)
