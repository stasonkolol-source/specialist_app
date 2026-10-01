"""Контракт модуля media для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из media только этот файл.
"""

from collections.abc import Collection
from typing import Protocol

from app.platform.kernel.ids import MediaId


class LegalHold(Protocol):
    """Удержание файлов (ADR-0016 §6): доказательства открытого кейса модерации (2.5a), а
    с 6.1c — и спора, не стираются, даже если автор удалил файл или аккаунт.

    Реализует модуль выше по DAG (moderation): media о нём не знает, связывает dishka.
    """

    async def held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        """Какие из файлов удерживаются сейчас. Читает в транзакции вызывающего."""
        ...
