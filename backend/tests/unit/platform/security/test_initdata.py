"""Проверка initData на эталонных векторах (DEVELOPMENT_PLAN 0.14, research/02 §3.2)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from aiogram.utils.web_app import check_webapp_signature
from pydantic import SecretStr

from app.platform.security.errors import InitDataExpiredError, InvalidInitDataError
from app.platform.security.initdata import InitDataVerifier, SharedContact, sign
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

BOT_TOKEN = "7000000001:TEST_ONLY_synthetic_bot_token"  # noqa: S105 — синтетический
OTHER_BOT_TOKEN = "7000000002:TEST_ONLY_synthetic_bot_token"  # noqa: S105 — синтетический
AUTH_DATE = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
USER = {
    "id": 279058397,
    "first_name": "Ana",
    "last_name": "Petrović",
    "username": "ana_ns",
    "language_code": "sr",
    "is_premium": True,
    "allows_write_to_pm": True,
}
FIELDS = {
    "auth_date": str(int(AUTH_DATE.timestamp())),
    "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
    "user": json.dumps(USER, separators=(",", ":"), ensure_ascii=False),
    "signature": "SIG_PLACEHOLDER_base64url",
}
REFERENCE_HASH = "19b966691edbe1a71022a9d1df417780021419e0db4a20f8bdf913171f230e76"
"""Хэш FIELDS под BOT_TOKEN, проверенный независимой реализацией aiogram."""


def init_data(fields: dict[str, str] = FIELDS, token: str = BOT_TOKEN, **extra: str) -> str:
    signed = fields | extra
    return urlencode(signed | {"hash": sign(signed, token)})


def verifier(now: datetime = AUTH_DATE + timedelta(minutes=5)) -> InitDataVerifier:
    return InitDataVerifier(SecretStr(BOT_TOKEN), FakeClock(now))


def test_reference_vector_matches_aiogram() -> None:
    assert sign(FIELDS, BOT_TOKEN) == REFERENCE_HASH
    assert check_webapp_signature(BOT_TOKEN, init_data())


def test_valid_initdata_gives_user_and_context() -> None:
    data = verifier().verify(init_data(start_param="job_abc"))
    assert data.user.id == 279058397
    assert data.user.last_name == "Petrović"
    assert data.user.language_code == "sr"
    assert data.user.is_premium
    assert data.auth_date == AUTH_DATE
    assert data.start_param == "job_abc"
    assert data.query_id == "AAHdF6IQAAAAAN0XohDhrOrc"


def test_signature_field_is_part_of_check_string() -> None:
    raw = init_data().replace("SIG_PLACEHOLDER", "SIG_REPLACED")
    with pytest.raises(InvalidInitDataError):
        verifier().verify(raw)


def test_uppercase_hash_is_accepted() -> None:
    raw = init_data()
    signed = sign(FIELDS, BOT_TOKEN)
    assert verifier().verify(raw.replace(signed, signed.upper())).user.id == USER["id"]


@pytest.mark.parametrize(
    ("age", "error"),
    [
        (timedelta(minutes=59, seconds=59), None),
        (timedelta(hours=1), None),
        (timedelta(hours=1, seconds=1), InitDataExpiredError),
        (timedelta(days=3), InitDataExpiredError),
        (timedelta(seconds=-60), None),
        (timedelta(seconds=-61), InvalidInitDataError),
    ],
)
def test_auth_date_window(age: timedelta, error: type[Exception] | None) -> None:
    check = verifier(now=AUTH_DATE + age)
    if error is None:
        check.verify(init_data())
    else:
        with pytest.raises(error):
            check.verify(init_data())


def test_substituted_user_is_rejected() -> None:
    forged = json.dumps(USER | {"id": 1}, separators=(",", ":"), ensure_ascii=False)
    raw = init_data().replace(urlencode({"user": FIELDS["user"]}), urlencode({"user": forged}))
    with pytest.raises(InvalidInitDataError):
        verifier().verify(raw)


def test_substituted_auth_date_is_rejected() -> None:
    fresh = str(int((AUTH_DATE + timedelta(hours=2)).timestamp()))
    raw = init_data().replace(f"auth_date={FIELDS['auth_date']}", f"auth_date={fresh}")
    with pytest.raises(InvalidInitDataError):
        verifier(now=AUTH_DATE + timedelta(hours=2)).verify(raw)


def test_other_bot_is_rejected() -> None:
    with pytest.raises(InvalidInitDataError):
        verifier().verify(init_data(token=OTHER_BOT_TOKEN))


def test_login_widget_secret_is_not_accepted() -> None:
    """Секрет Login Widget — SHA256(token); путать алгоритмы нельзя (research/02 §3.2)."""
    check = "\n".join(f"{k}={FIELDS[k]}" for k in sorted(FIELDS))
    widget_hash = hmac.new(
        hashlib.sha256(BOT_TOKEN.encode()).digest(), check.encode(), hashlib.sha256
    ).hexdigest()
    with pytest.raises(InvalidInitDataError):
        verifier().verify(urlencode(FIELDS | {"hash": widget_hash}))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        urlencode(FIELDS),
        urlencode(FIELDS | {"hash": ""}),
        urlencode(FIELDS | {"hash": "zz"}),
        "hash=%D1%8F",
        urlencode(FIELDS | {"hash": "я" * 64}),
        "hash=%FF",
        init_data() + "&hash=" + "0" * 64,
        init_data() + "&user=%7B%7D",
        "a" * 9000,
        "%%%",
        "just-text",
    ],
    ids=[
        "empty",
        "no-hash",
        "empty-hash",
        "short-hash",
        "non-ascii-hash",
        "non-ascii-hash-64-chars",
        "hash-invalid-utf8",
        "duplicate-hash",
        "duplicate-user",
        "too-long",
        "bad-encoding",
        "not-a-query",
    ],
)
def test_malformed_initdata_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidInitDataError):
        verifier().verify(raw)


@pytest.mark.parametrize(
    "fields",
    [
        {k: v for k, v in FIELDS.items() if k != "user"},
        FIELDS | {"user": "not json"},
        FIELDS | {"user": json.dumps({"first_name": "Ana"})},
        FIELDS | {"user": json.dumps({"id": "279058397", "first_name": "Ana"})},
        FIELDS | {"user": json.dumps([1, 2])},
        FIELDS | {"auth_date": "soon"},
        {k: v for k, v in FIELDS.items() if k != "auth_date"},
    ],
    ids=[
        "no-user",
        "user-not-json",
        "user-no-id",
        "user-id-string",
        "user-list",
        "bad-date",
        "no-date",
    ],
)
def test_signed_but_incomplete_initdata_is_rejected(fields: dict[str, str]) -> None:
    with pytest.raises(InvalidInitDataError):
        verifier().verify(init_data(fields))


def test_errors_do_not_carry_initdata() -> None:
    with pytest.raises(InvalidInitDataError) as caught:
        verifier().verify(init_data(token=OTHER_BOT_TOKEN))
    assert "ana_ns" not in str(caught.value)
    assert caught.value.params == {}


def contact_response(contact: object, *, token: str = BOT_TOKEN) -> str:
    """Ответ `requestContact`: поле `contact` (JSON), `auth_date` и подпись, как у initData."""
    fields = {"auth_date": FIELDS["auth_date"], "contact": json.dumps(contact)}
    return urlencode(fields | {"hash": sign(fields, token)})


def test_shared_contact_gives_the_phone_and_its_owner() -> None:
    raw = contact_response(
        {"user_id": USER["id"], "phone_number": "381641234567", "first_name": "Ana"}
    )

    assert verifier().verify_contact(raw) == SharedContact(
        user_id=279058397, phone_e164="+381641234567"
    )


@pytest.mark.parametrize(
    "contact",
    [
        {"phone_number": "381641234567"},  # без владельца
        {"user_id": 1, "phone_number": "64 123"},  # не номер
        {"user_id": 1, "phone_number": "1" * 16},  # длиннее E.164
        ["381641234567"],
    ],
)
def test_malformed_contact_is_rejected(contact: object) -> None:
    with pytest.raises(InvalidInitDataError):
        verifier().verify_contact(contact_response(contact))


def test_contact_of_another_bot_or_stale_is_rejected() -> None:
    contact = {"user_id": USER["id"], "phone_number": "+381641234567"}
    with pytest.raises(InvalidInitDataError):
        verifier().verify_contact(contact_response(contact, token=OTHER_BOT_TOKEN))
    with pytest.raises(InitDataExpiredError):
        verifier(now=AUTH_DATE + timedelta(hours=2)).verify_contact(contact_response(contact))
    with pytest.raises(InvalidInitDataError):
        verifier().verify_contact(init_data())  # initData без контакта — не контакт
