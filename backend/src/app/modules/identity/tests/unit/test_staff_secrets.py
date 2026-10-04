"""Пароль и TOTP персонала (2.7a): argon2 и RFC 6238 с допуском в один шаг; секреты — не в repr."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from app.modules.identity.application.dto import StaffCredentialsSet
from app.modules.identity.application.ports import StaffCredential
from app.modules.identity.application.use_cases.create_staff_login import CreateStaffLoginCommand
from app.modules.identity.infrastructure.staff import TOTP_STEP, PwdlibStaffSecrets
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 4, 12, 0, 10, tzinfo=UTC)


def test_password_is_hashed_with_argon2_and_verified() -> None:
    secrets = PwdlibStaffSecrets()
    hashed = secrets.hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert secrets.verify_password("correct horse battery", hashed)
    assert not secrets.verify_password("wrong horse battery", hashed)
    assert not secrets.verify_password("anything", "not-a-hash")


def test_totp_code_maps_to_its_step_within_one_step() -> None:
    secrets = PwdlibStaffSecrets()
    secret = secrets.new_totp_secret()
    totp = pyotp.TOTP(secret, interval=TOTP_STEP)
    step = int(NOW.timestamp()) // TOTP_STEP
    assert secrets.totp_step(secret, totp.at(NOW), NOW) == step
    assert secrets.totp_step(secret, totp.at(NOW - timedelta(seconds=30)), NOW) == step - 1
    assert secrets.totp_step(secret, totp.at(NOW + timedelta(seconds=30)), NOW) == step + 1
    assert secrets.totp_step(secret, totp.at(NOW - timedelta(seconds=90)), NOW) is None
    assert secrets.totp_step(secret, "", NOW) is None
    assert secrets.totp_step(secret, "12345a", NOW) is None
    assert secrets.totp_uri(secret, "ana").startswith("otpauth://totp/")


def test_secrets_stay_out_of_repr() -> None:
    """Хэш пароля, секрет TOTP и токены не попадают в repr: в логи и трейсы ошибок."""
    secrets = PwdlibStaffSecrets()
    password = "correct horse battery"  # noqa: S105 — пароль теста
    hashed = secrets.hash_password(password)
    secret = secrets.new_totp_secret()
    user_id = UserId(new_id())
    credential = StaffCredential(
        user_id=user_id,
        login="ana",
        password_hash=hashed,
        encrypted_totp_secret=f"v1:00000000:{secret}",
        totp_last_step=None,
    )
    created = StaffCredentialsSet(
        user_id=user_id,
        login="ana",
        totp_secret=secret,
        totp_uri=secrets.totp_uri(secret, "ana"),
        replaced=False,
    )
    command = CreateStaffLoginCommand(telegram_id=1, login="ana", password=password)
    for shown in (repr(credential), repr(created), repr(command)):
        assert hashed not in shown
        assert secret not in shown
        assert password not in shown
        assert "ana" in shown  # остальные поля — на месте
