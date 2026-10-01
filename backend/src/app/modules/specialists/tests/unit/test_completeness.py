"""Полнота профиля для кабинета S33 (DEVELOPMENT_PLAN 2.10): процент и подсказки по порядку."""

import pytest

from app.modules.specialists.domain.completeness import (
    ABOUT_ENOUGH,
    Completeness,
    Hint,
    completeness,
)
from app.modules.specialists.domain.profile import ProfileKind, WorkMode

pytestmark = pytest.mark.unit

ABOUT = "Электрик, 12 лет опыта. " * 4


def filled(
    *,
    kind: ProfileKind = ProfileKind.PRO,
    about: str | None = ABOUT,
    work_modes: tuple[WorkMode, ...] = (WorkMode.AT_CLIENT,),
    area_ids: tuple[int, ...] = (11,),
    price_items: int = 3,
    undescribed_prices: int = 0,
) -> Completeness:
    """Заполненный профиль электрика с правками по месту."""
    return completeness(
        kind=kind,
        category_ids=(101,),
        headline="Электрик · мелкий ремонт",
        about=about,
        languages=("ru", "sr"),
        work_modes=work_modes,
        area_ids=area_ids,
        price_items=price_items,
        undescribed_prices=undescribed_prices,
    )


def test_new_draft_has_nothing_and_asks_for_the_basics_first() -> None:
    empty = completeness(
        kind=ProfileKind.PRO,
        category_ids=(),
        headline=None,
        about=None,
        languages=(),
        work_modes=(),
        area_ids=(),
        price_items=0,
        undescribed_prices=0,
    )

    assert empty.percent == 0
    # про описания позиций — только когда позиции есть
    assert [hint.code for hint in empty.hints] == [
        "category_ids",
        "headline",
        "about",
        "languages",
        "area_ids",
        "services",
    ]


def test_full_specialist_profile_is_complete() -> None:
    assert filled() == Completeness(percent=100, hints=())


def test_counts_price_items_without_description() -> None:
    assert filled(undescribed_prices=4) == Completeness(
        percent=90, hints=(Hint("service_descriptions", 4),)
    )


def test_short_about_asks_for_more() -> None:
    assert len("Электрик") < ABOUT_ENOUGH
    assert filled(about="Электрик") == Completeness(percent=80, hints=(Hint("about"),))


def test_side_job_needs_no_price_list_and_at_own_place_needs_no_districts() -> None:
    casual = filled(
        kind=ProfileKind.CASUAL,
        work_modes=(WorkMode.AT_OWN_PLACE,),
        area_ids=(),
        price_items=0,
    )

    assert casual == Completeness(percent=100, hints=())
