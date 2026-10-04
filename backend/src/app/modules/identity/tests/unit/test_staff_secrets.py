"""Пароль и TOTP персонала (2.7a): argon2 и RFC 6238 с допуском в один шаг."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from app.modules.identity.infrastructure.staff import TOTP_STEP, PwdlibStaffSecrets

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
