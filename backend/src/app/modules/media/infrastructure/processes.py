"""Дочерние процессы обработки медиа (Pillow, ffmpeg): что им достаётся от воркера."""

import os

ENVIRONMENT = ("PATH", "PYTHONPATH", "LANG", "LC_ALL", "TMPDIR", "HOME")
"""Что процесс видит из окружения воркера: без DSN, ключей S3 и токенов."""


def child_environment() -> dict[str, str]:
    """Белый список окружения: не настройки приложения, а изоляция недоверенного процесса."""
    environ = os.environ  # noqa: TID251 — секреты воркера дочернему процессу не передаём
    return {name: environ[name] for name in ENVIRONMENT if name in environ}
