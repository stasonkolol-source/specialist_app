"""Секреты в БД под ключом приложения (шаг 8.4; ASVS V6): AES-256-GCM, версия формата и id ключа.

Формат записи — `v1:<kid>:<base64url(nonce ‖ шифротекст ‖ тег)>`:
- kid — 8 hex от SHA-256 ключа: по нему при ротации выбирается ключ. Текущий шифрует и
  расшифровывает, прежний только расшифровывает — запись под ним помечается `stale`, её
  перешифровывают текущим;
- nonce — 12 случайных байт на каждую запись: повтор nonce под одним ключом ломает GCM, а случайный
  безопасен до ~2³² записей на ключ — у нас их десятки;
- связанные данные (AAD) — версия, kid и контекст записи (например, id сотрудника): шифротекст,
  перенесённый в чужую строку, не расшифруется.

Любая ошибка расшифровки — отказ без подробностей (fail closed): чужой ключ, подмена и порча
снаружи неразличимы. Ни ключ, ни открытый текст в исключения и repr не попадают.
"""

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION: Final = "v1"
KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
_SEALED: Final = re.compile(r"v1:(?P<kid>[0-9a-f]{8}):(?P<body>[A-Za-z0-9_-]+)")


class SealedSecretError(ValueError):
    """Запись не расшифровать: неизвестный формат или ключ, подмена, порча — без подробностей."""


@dataclass(frozen=True, slots=True)
class Opened:
    plaintext: str = field(repr=False)
    stale: bool
    """Зашифровано прежним ключом: перешифровать текущим (`SecretBox.seal`)."""


class SecretBox:
    """AES-256-GCM с текущим и (на время ротации) прежним ключом."""

    def __init__(self, key: bytes, previous: bytes | None = None) -> None:
        if len(key) != KEY_BYTES or (previous is not None and len(previous) != KEY_BYTES):
            raise ValueError(f"AES-256 key must be {KEY_BYTES} bytes")
        self._kid = key_id(key)
        self._current = AESGCM(key)
        self._keys = {self._kid: self._current}
        if previous is not None and key_id(previous) != self._kid:
            self._keys[key_id(previous)] = AESGCM(previous)

    def seal(self, plaintext: str, *, context: str) -> str:
        nonce = secrets.token_bytes(NONCE_BYTES)
        data = self._current.encrypt(nonce, plaintext.encode(), _aad(self._kid, context))
        body = base64.urlsafe_b64encode(nonce + data).rstrip(b"=").decode()
        return f"{VERSION}:{self._kid}:{body}"

    def open(self, sealed: str, *, context: str) -> Opened:
        """SealedSecretError — не та версия, неизвестный ключ, подмена или порча."""
        found = _SEALED.fullmatch(sealed)
        aead = self._keys.get(found["kid"]) if found else None
        if found is None or aead is None:
            raise SealedSecretError
        body = found["body"]
        try:
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            if len(raw) < NONCE_BYTES + TAG_BYTES:
                raise SealedSecretError
            plaintext = aead.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], _aad(found["kid"], context)
            ).decode()
        except binascii.Error, InvalidTag, UnicodeDecodeError:
            raise SealedSecretError from None
        return Opened(plaintext=plaintext, stale=found["kid"] != self._kid)


def is_sealed(value: str) -> bool:
    """Запись этого формата (любой версии `vN:`), а не открытый текст."""
    return re.match(r"v\d+:", value) is not None


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"sosed-secretbox-kid:" + key).hexdigest()[:8]


def _aad(kid: str, context: str) -> bytes:
    return f"{VERSION}:{kid}:{context}".encode()
