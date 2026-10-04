"""Секрет TOTP персонала в БД (8.4): шифрование ключом APP_TOTP_KEY, строки до 8.4, ротация."""

import secrets

import pytest
from pydantic import SecretStr

from app.modules.identity.di import DEV_TOTP_KEY, totp_box
from app.modules.identity.infrastructure.staff import AesGcmTotpCipher, PwdlibStaffSecrets
from app.platform.kernel.ids import UserId, new_id
from app.platform.security.secretbox import SecretBox, key_id
from app.platform.settings import AppSettings, Environment, SettingsError

pytestmark = pytest.mark.unit

KEY = secrets.token_bytes(32)
OLD_KEY = secrets.token_bytes(32)
SECRET = PwdlibStaffSecrets().new_totp_secret()


def test_secret_is_stored_encrypted_and_bound_to_the_staff_member() -> None:
    cipher = AesGcmTotpCipher(SecretBox(KEY))
    secret = PwdlibStaffSecrets().new_totp_secret()
    ana, bob = UserId(new_id()), UserId(new_id())
    stored = cipher.encrypt(secret, ana)
    assert stored.startswith("v1:")
    assert secret not in stored
    opened = cipher.decrypt(stored, ana)
    assert opened is not None
    assert (opened.value, opened.stale) == (secret, False)
    assert secret not in repr(opened)
    assert cipher.decrypt(stored, bob) is None  # чужая строка — не расшифровать


def test_wrong_key_or_damage_fails_closed() -> None:
    ana = UserId(new_id())
    stored = AesGcmTotpCipher(SecretBox(OLD_KEY)).encrypt(SECRET, ana)
    cipher = AesGcmTotpCipher(SecretBox(KEY))
    assert cipher.decrypt(stored, ana) is None
    assert cipher.decrypt(stored[:-4] + "AAAA", ana) is None
    assert cipher.decrypt("not a secret", ana) is None  # не base32 и не шифротекст


def test_legacy_plaintext_row_is_read_and_marked_for_reencryption() -> None:
    cipher = AesGcmTotpCipher(SecretBox(KEY))
    ana = UserId(new_id())
    secret = PwdlibStaffSecrets().new_totp_secret()
    opened = cipher.decrypt(secret, ana)  # строка до 8.4: base32 открытым текстом
    assert opened is not None
    assert (opened.value, opened.stale) == (secret, True)


def test_previous_key_decrypts_and_reencrypts_with_the_current_one() -> None:
    ana = UserId(new_id())
    stored = AesGcmTotpCipher(SecretBox(OLD_KEY)).encrypt(SECRET, ana)
    rotated = AesGcmTotpCipher(SecretBox(KEY, previous=OLD_KEY))
    opened = rotated.decrypt(stored, ana)
    assert opened is not None
    assert (opened.value, opened.stale) == (SECRET, True)
    assert rotated.encrypt(opened.value, ana).startswith(f"v1:{key_id(KEY)}:")


def test_key_comes_from_settings_and_dev_key_only_outside_stage_and_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("APP_TOTP_KEY", "APP_TOTP_KEY_PREVIOUS"):
        monkeypatch.delenv(name, raising=False)
    dev = totp_box(AppSettings(_env_file=None, env=Environment.DEV))  # type: ignore[call-arg]
    assert dev.seal("x", context="c").startswith(f"v1:{key_id(DEV_TOTP_KEY)}:")
    own = AppSettings(  # type: ignore[call-arg]
        _env_file=None,
        env=Environment.PRODUCTION,
        totp_key=SecretStr(KEY.hex()),
        totp_key_previous=SecretStr(OLD_KEY.hex()),
    )
    rotated = totp_box(own)
    assert rotated.seal("x", context="c").startswith(f"v1:{key_id(KEY)}:")
    assert rotated.open(SecretBox(OLD_KEY).seal("x", context="c"), context="c").stale
    for env in (Environment.STAGE, Environment.PRODUCTION):
        with pytest.raises(SettingsError, match="APP_TOTP_KEY"):
            totp_box(AppSettings(_env_file=None, env=env))  # type: ignore[call-arg]
