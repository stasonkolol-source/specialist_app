"""Имя автора отзыва на карточке специалиста: «Имя Ф.» (DEVELOPMENT_PLAN 7.2)."""

import pytest

from app.platform.text.names import short_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("full", "short"),
    [
        ("Ana Petrović", "Ana P."),
        ("Елена Кузнецова", "Елена К."),
        ("Mary Jane watson", "Mary W."),
        ("Ирина", "Ирина"),
        ("  Đorđe   đokić ", "Đorđe Đ."),
        ("", ""),
    ],
)
def test_first_name_and_initial_of_the_last(full: str, short: str) -> None:
    assert short_name(full) == short
