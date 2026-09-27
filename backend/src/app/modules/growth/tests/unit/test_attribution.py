"""Первое касание: тип ссылки, реферальный суффикс и сырой код (DEVELOPMENT_PLAN 1.4b)."""

import pytest

from app.modules.growth.domain.attribution import AttributionSource, FirstTouch
from app.platform.contracts.events.identity import EntryPoint

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("start_param", [None, ""])
def test_without_code_is_organic(start_param: str | None) -> None:
    touch = FirstTouch.of(start_param, entry_point=EntryPoint.MINI_APP)
    assert touch == FirstTouch(
        source=AttributionSource.ORGANIC,
        start_param=None,
        referral_code=None,
        entry_point=EntryPoint.MINI_APP,
    )


@pytest.mark.parametrize(
    ("start_param", "source", "ref"),
    [
        ("j_02y9UKmeRG6vSNbdsEYkkR", AttributionSource.JOB, None),
        ("s_02yBkPi1NksSnHWzckDH0V_rAB12CD", AttributionSource.SPECIALIST, "AB12CD"),
        ("c_031xzEWS7WFYMsmk7f0c1P", AttributionSource.CHAT, None),
        ("d_3Nf1YTX8urRqobGWgo1mmN", AttributionSource.DEAL, None),
        ("h_rCHAN1", AttributionSource.HOME, "CHAN1"),
        ("gh_rCHAN1", AttributionSource.GOODS, "CHAN1"),
    ],
)
def test_link_type_and_referral_suffix(
    start_param: str, source: AttributionSource, ref: str | None
) -> None:
    touch = FirstTouch.of(start_param, entry_point=EntryPoint.BOT)
    assert (touch.source, touch.referral_code, touch.start_param) == (source, ref, start_param)
    assert touch.entry_point is EntryPoint.BOT


def test_unknown_code_keeps_raw_value_in_telegram_syntax() -> None:
    touch = FirstTouch.of("x_1Xh3kQ9vB7mZ2pR4sT8dLq", entry_point=None)
    assert (touch.source, touch.start_param, touch.referral_code) == (
        AttributionSource.UNKNOWN,
        "x_1Xh3kQ9vB7mZ2pR4sT8dLq",
        None,
    )


@pytest.mark.parametrize("start_param", ["_tgr_abc", "h" * 65, "hello world"])
def test_foreign_or_malformed_code_is_unknown_without_raw_value(start_param: str) -> None:
    touch = FirstTouch.of(start_param, entry_point=EntryPoint.MINI_APP)
    assert (touch.source, touch.start_param) == (AttributionSource.UNKNOWN, None)
