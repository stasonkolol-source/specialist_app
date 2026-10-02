"""Кэш ответов в Valkey (ARCHITECTURE §9.7): JSON по ключу со сроком жизни.

Кэш — ускорение, не источник данных: недоступный Valkey значит промах, а не ошибку.
Ключи — `<модуль>.<что>:…` (`search.suggest:v1:elek`); версия в ключе меняет формат значения
без сброса базы.
"""

from datetime import timedelta
from typing import Protocol


class JsonCache(Protocol):
    async def get(self, key: str) -> object | None:
        """Значение или None: нет ключа, истёк срок, Valkey недоступен."""
        ...

    async def set(self, key: str, value: object, *, ttl: timedelta) -> None:
        """Записать значение, которое переводится в JSON; Valkey недоступен — молча."""
        ...
