"""Правила запроса выдачи (DEVELOPMENT_PLAN 4.2): текст, веса, расстояние, курсор."""

import base64
import json
import math

import pytest

from app.modules.search.domain.query import (
    MAX_OFFSET,
    MAX_QUERY,
    PageCursor,
    QueryText,
    RankWeights,
    Stage,
    rounded_distance,
)
from app.platform.kernel.pagination import InvalidCursorError

pytestmark = pytest.mark.unit


def test_query_text_drops_serbian_stopwords_and_spells_dj_out() -> None:
    text = QueryText.parse("  Popravka   i  građevina za stan ")

    assert text is not None
    assert text.raw == "Popravka i građevina za stan"
    assert text.words == ("Popravka", "gradjevina", "stan")


def test_query_text_drops_cyrillic_stopwords_too() -> None:
    text = QueryText.parse("Мајстор за купатило")

    assert text is not None
    assert text.words == ("Мајстор", "купатило")


@pytest.mark.parametrize("q", [None, "", "   ", "i za na", "!!!"])
def test_nothing_to_search_is_no_text(q: str | None) -> None:
    assert QueryText.parse(q) is None


def test_long_query_is_cut() -> None:
    text = QueryText.parse("электрик " * 50)

    assert text is not None
    assert len(text.raw) <= MAX_QUERY


def test_fts_text_joins_words_for_each_stage() -> None:
    text = QueryText.parse("ремонт ванной")

    assert text is not None
    assert text.fts(Stage.ALL_WORDS) == "ремонт ванной"
    assert text.fts(Stage.PREFIX) == "ремонт ванной"
    assert text.fts(Stage.ANY_WORD) == "ремонт or ванной"


def test_weights_from_flag_override_only_valid_known_keys() -> None:
    weights = RankWeights.from_flag(
        {"text": 0.5, "rating": -1, "trust": True, "activity": math.nan, "price": 1, "x": "y"}
    )

    assert weights == RankWeights(text=0.5)


@pytest.mark.parametrize("value", [None, "0.5", [0.1], 3])
def test_weights_without_mapping_are_defaults(value: object) -> None:
    assert RankWeights.from_flag(value) == RankWeights()


@pytest.mark.parametrize(
    ("meters", "shown"),
    [(None, None), (0.0, 500), (240.0, 500), (1_300.0, 1_500), (1_740.0, 1_500), (9_990.0, 10_000)],
)
def test_distance_is_rounded_to_half_a_kilometre(meters: float | None, shown: int | None) -> None:
    assert rounded_distance(meters) == shown


def test_cursor_round_trip() -> None:
    cursor = PageCursor(Stage.PREFIX, 40)

    assert PageCursor.decode(cursor.encode()) == cursor


def _raw(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "bm90IGpzb24",
        _raw(["nope", 20]),
        _raw(["all", 0]),
        _raw(["all", MAX_OFFSET + 20]),
        _raw(["all", True]),
        _raw(["all", "20"]),
        _raw({"stage": "all"}),
        _raw(["all"]),
    ],
)
def test_broken_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        PageCursor.decode(cursor)
