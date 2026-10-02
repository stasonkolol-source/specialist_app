"""Данные callback-кнопок бота (DEVELOPMENT_PLAN 5.1): туда и обратно, в пределах 64 байт."""

from uuid import UUID

import pytest

from app.platform.telegram.callbacks import (
    MAX_CALLBACK_DATA,
    CallbackAction,
    CallbackData,
    encode_callback,
    parse_callback,
)

pytestmark = pytest.mark.unit

MAX_UUID = UUID(int=(1 << 128) - 1)


@pytest.mark.parametrize(
    "data",
    [
        CallbackData(CallbackAction.JOB_EXTEND, UUID("01a0fc88-f156-726a-9a76-99e3d10e5542")),
        CallbackData(CallbackAction.JOB_CLOSE, MAX_UUID, "found"),
        CallbackData(CallbackAction.JOB_CLOSE, MAX_UUID, "hired_elsewhere"),
    ],
)
def test_round_trip_fits_the_bot_api_limit(data: CallbackData) -> None:
    raw = encode_callback(data)

    assert parse_callback(raw) == data
    assert len(raw.encode()) <= MAX_CALLBACK_DATA


def test_format_is_action_base62_and_argument() -> None:
    raw = encode_callback(CallbackData(CallbackAction.JOB_CLOSE, UUID(int=0), "found"))

    assert raw == "jc:0000000000000000000000:found"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "avail:22",  # своя кнопка specialists, не кодек
        "jx",
        "zz:0000000000000000000000",
        "jx:short",
        "jx:0000000000000000000000:Bad-Arg",
        "jx:0000000000000000000000:a:b",
        "jc:" + "z" * 22,  # больше 2^128 − 1
    ],
)
def test_foreign_or_broken_data_is_not_parsed(raw: str | None) -> None:
    assert parse_callback(raw) is None


def test_argument_must_be_a_code() -> None:
    with pytest.raises(ValueError, match="not a code"):
        CallbackData(CallbackAction.JOB_CLOSE, UUID(int=1), "два слова")
