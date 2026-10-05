"""Даты для людей (ADR-0013): по Белграду, сербский месяц после предлога — в родительном."""

from datetime import UTC, datetime

import pytest

from app.platform.i18n.dates import long_datetime, serbian_genitive
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit

# 08:30 по Белграду 12 октября 2026 (UTC+2)
MOMENT = datetime(2026, 10, 12, 6, 30, tzinfo=UTC)


def test_long_datetime_is_nominative_by_default() -> None:
    assert long_datetime(MOMENT, Locale.SR_LATN) == "12. oktobar 2026. 08:30"
    assert long_datetime(MOMENT, Locale.SR_CYRL) == "12. октобар 2026. 08:30"


def test_genitive_declines_the_serbian_month_after_a_preposition() -> None:
    assert long_datetime(MOMENT, Locale.SR_LATN, genitive=True) == "12. oktobra 2026. 08:30"
    assert long_datetime(MOMENT, Locale.SR_CYRL, genitive=True) == "12. октобра 2026. 08:30"


def test_genitive_keeps_russian_and_english() -> None:
    for locale in (Locale.RU, Locale.EN):
        assert long_datetime(MOMENT, locale, genitive=True) == long_datetime(MOMENT, locale)
    assert long_datetime(MOMENT, Locale.RU, genitive=True) == "12 октября 2026 г., 08:30"


def test_month_is_taken_in_belgrade_time() -> None:
    # 23:30 UTC 30 сентября — уже 1 октября в Белграде
    late = datetime(2026, 9, 30, 23, 30, tzinfo=UTC)
    assert long_datetime(late, Locale.SR_LATN, genitive=True) == "1. oktobra 2026. 01:30"


@pytest.mark.parametrize(
    ("nominative", "genitive"),
    [
        ("januar", "januara"),
        ("februar", "februara"),
        ("mart", "marta"),
        ("april", "aprila"),
        ("maj", "maja"),
        ("jun", "juna"),
        ("jul", "jula"),
        ("avgust", "avgusta"),
        ("septembar", "septembra"),
        ("oktobar", "oktobra"),
        ("novembar", "novembra"),
        ("decembar", "decembra"),
        ("март", "марта"),
        ("децембар", "децембра"),
        ("oktobra", "oktobra"),  # уже родительный — как есть
    ],
)
def test_serbian_genitive_of_every_month(nominative: str, genitive: str) -> None:
    assert serbian_genitive(nominative) == genitive
