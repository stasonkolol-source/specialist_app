"""Секреты в БД под ключом приложения (8.4; ASVS V6): AES-256-GCM, kid и прежний ключ ротации."""

import base64
import secrets

import pytest

from app.platform.security.secretbox import SealedSecretError, SecretBox, is_sealed, key_id

pytestmark = pytest.mark.unit

KEY = secrets.token_bytes(32)
OLD_KEY = secrets.token_bytes(32)
SECRET = base64.b32encode(secrets.token_bytes(20)).decode()
"""Секрет TOTP (base32), как его даёт pyotp."""


def test_round_trip_with_version_and_key_id() -> None:
    box = SecretBox(KEY)
    sealed = box.seal(SECRET, context="row-1")
    assert sealed.startswith(f"v1:{key_id(KEY)}:")
    assert SECRET not in sealed
    assert is_sealed(sealed)
    assert not is_sealed(SECRET)
    opened = box.open(sealed, context="row-1")
    assert (opened.plaintext, opened.stale) == (SECRET, False)
    assert SECRET not in repr(opened)
    # nonce случайный: одна и та же запись дважды даёт разные шифротексты
    assert box.seal(SECRET, context="row-1") != sealed


def test_wrong_key_fails_closed() -> None:
    sealed = SecretBox(OLD_KEY).seal(SECRET, context="row-1")
    with pytest.raises(SealedSecretError):
        SecretBox(KEY).open(sealed, context="row-1")


def test_tampered_or_moved_ciphertext_is_rejected() -> None:
    box = SecretBox(KEY)
    sealed = box.seal(SECRET, context="row-1")
    head, body = sealed.rsplit(":", 1)
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    for bad in (
        f"{head}:{flipped}",  # подмена шифротекста или тега
        f"{head}:{body[:20]}",  # обрезано: короче nonce и тега
        f"{head}:{body[:-3]}",  # 77 знаков: такой длины у base64 не бывает
        sealed.replace("v1:", "v2:", 1),  # неизвестная версия формата
        SECRET,  # открытый текст — не запись
    ):
        with pytest.raises(SealedSecretError):
            box.open(bad, context="row-1")
    with pytest.raises(SealedSecretError):  # контекст (AAD): шифротекст из чужой строки
        box.open(sealed, context="row-2")


def test_previous_key_decrypts_as_stale_and_reseals_with_current() -> None:
    sealed = SecretBox(OLD_KEY).seal(SECRET, context="row-1")
    rotated = SecretBox(KEY, previous=OLD_KEY)
    opened = rotated.open(sealed, context="row-1")
    assert (opened.plaintext, opened.stale) == (SECRET, True)
    resealed = rotated.seal(opened.plaintext, context="row-1")
    assert resealed.startswith(f"v1:{key_id(KEY)}:")
    assert rotated.open(resealed, context="row-1").stale is False
    # прежний ключ убран после перешифровки — старая запись больше не читается
    with pytest.raises(SealedSecretError):
        SecretBox(KEY).open(sealed, context="row-1")


def test_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox(b"short")
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox(KEY, previous=b"short")
