"""Хелперы platform/db без БД: курсоры keyset, перевод ограничений, проверка версии."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.platform.db.constraints import constraint_name, raise_domain_error
from app.platform.db.query import InvalidCursorError, decode_cursor, encode_cursor
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.errors import ConflictError
from app.platform.kernel.ids import new_id

pytestmark = pytest.mark.unit


def test_cursor_roundtrip() -> None:
    moment = datetime(2026, 10, 5, 9, 0, 1, 123456, tzinfo=UTC)
    uid = new_id()
    cursor = encode_cursor(moment, uid, 42)
    assert "=" not in cursor
    assert decode_cursor(cursor, (datetime, type(uid), int)) == (moment, uid, 42)


@pytest.mark.parametrize("garbage", ["", "@@@", "bm90LWpzb24", encode_cursor(1)])
def test_invalid_cursor(garbage: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(garbage, (datetime, int))


class TakenError(ConflictError):
    code = "taken"


def _integrity(name: str | None) -> IntegrityError:
    orig = Exception("duplicate")
    orig.diag = SimpleNamespace(constraint_name=name)  # type: ignore[attr-defined]
    return IntegrityError("INSERT …", {}, orig)


def test_known_constraint_becomes_domain_error() -> None:
    err = _integrity("uq_widgets_owner_id_title")
    assert constraint_name(err) == "uq_widgets_owner_id_title"
    with pytest.raises(TakenError):
        raise_domain_error(err, {"uq_widgets_owner_id_title": TakenError})


def test_unknown_constraint_is_reraised_as_is() -> None:
    err = _integrity("fk_something")
    with pytest.raises(IntegrityError):
        raise_domain_error(err, {"uq_widgets_owner_id_title": TakenError})
    with pytest.raises(IntegrityError):
        raise_domain_error(_integrity(None), {})


def test_check_loaded_version() -> None:
    check_loaded_version(entity="job", loaded=3, expected=3)
    with pytest.raises(StaleDataError, match="job"):
        check_loaded_version(entity="job", loaded=4, expected=3)
