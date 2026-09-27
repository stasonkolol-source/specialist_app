"""Каталоги и Translator (DEVELOPMENT_PLAN 1.2, ADR-0013)."""

import shutil
from pathlib import Path

import pytest

from app.platform.i18n.catalogs import (
    LOCALES_DIR,
    catalog_path,
    generate_sr_latn,
    read_catalog,
    stale_sr_latn,
)
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit


def test_repository_catalogs_are_consistent() -> None:
    ru = set(read_catalog(catalog_path(Locale.RU)))
    assert ru == set(read_catalog(catalog_path(Locale.SR_CYRL)))
    assert ru == set(read_catalog(catalog_path(Locale.SR_LATN)))
    assert not stale_sr_latn()


def test_translator_follows_fallback_chain() -> None:
    translator = Translator(
        {
            Locale.RU: {"a": "ru-a", "b": "ru-b"},
            Locale.SR_CYRL: {"a": "Пажња {name}"},
            Locale.SR_LATN: {"a": "Pažnja {name}"},
        }
    )
    assert translator.text("a", Locale.SR_LATN, name="Ана") == "Pažnja Ана"
    assert translator.text("b", Locale.SR_CYRL) == "ru-b"
    assert translator.text("a", Locale.EN) == "ru-a"
    assert translator.text("missing", Locale.RU) is None
    assert translator.text("a", Locale.SR_CYRL) == "Пажња {name}"  # нет параметра — как есть


def test_loaded_translator_reads_repository_catalogs() -> None:
    translator = Translator.load()
    assert translator.text("errors.account_deleted", Locale.SR_LATN) == "Nalog je obrisan."
    assert "errors.not_found" in translator.keys(Locale.RU)


def test_stale_sr_latn_is_detected(tmp_path: Path) -> None:
    shutil.copytree(LOCALES_DIR, tmp_path / "locales")
    directory = tmp_path / "locales"
    assert not stale_sr_latn(directory)
    source = catalog_path(Locale.SR_CYRL, directory)
    source.write_text(
        source.read_text(encoding="utf-8").replace("Није пронађено.", "Нема га."), encoding="utf-8"
    )
    assert stale_sr_latn(directory)
    target = catalog_path(Locale.SR_LATN, directory)
    target.write_text(generate_sr_latn(source.read_text(encoding="utf-8")), encoding="utf-8")
    assert not stale_sr_latn(directory)
    assert read_catalog(target)["errors.not_found"] == "Nema ga."


def test_generator_keeps_keys_comments_and_header() -> None:
    source = (
        '# коментар\nmsgid ""\nmsgstr ""\n"Language: sr_Cyrl\\n"\n"MIME-Version: 1.0\\n"\n\n'
        'msgid "errors.x"\nmsgstr ""\n"Пажња: "\n"Љубав"\n'
    )
    generated = generate_sr_latn(source)
    assert "# коментар" in generated
    assert '"Language: sr_Latn\\n"' in generated
    assert 'msgid "errors.x"' in generated
    assert '"Pažnja: "\n"Ljubav"' in generated
