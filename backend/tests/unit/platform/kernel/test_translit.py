"""Транслитерация sr-Cyrl → sr-Latn (ARCHITECTURE §7.4, DEVELOPMENT_PLAN 1.2)."""

import pytest

from app.platform.kernel.translit import sr_cyrl_to_latn

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("cyrillic", "latin"),
    [
        ("Електричар", "Električar"),
        ("Ђорђе Шћепановић", "Đorđe Šćepanović"),
        ("љубав њега џемпер", "ljubav njega džemper"),
        ("Љубав Његош Џеп", "Ljubav Njegoš Džep"),
        ("ЉУБАВ ЊЕГОШ ЏЕП", "LJUBAV NJEGOŠ DŽEP"),
        ("КЊ", "KNJ"),
        ("Љ", "Lj"),
        ("ЧИШЋЕЊЕ стана", "ČIŠĆENJE stana"),
        ("абвгдђежзијклљмнњопрстћуфхцчџш", "abvgdđežzijklljmnnjoprstćufhcčdžš"),
        ("Нови Сад, 2026 — 5000 RSD", "Novi Sad, 2026 — 5000 RSD"),
        ("Уже латиница: Novi Sad", "Uže latinica: Novi Sad"),
        ("Русский: щука, ы, э", "Russkiй: щuka, ы, э"),  # только сербские буквы
        ("", ""),
    ],
)
def test_transliteration(cyrillic: str, latin: str) -> None:
    assert sr_cyrl_to_latn(cyrillic) == latin
