"""Присутствие в диалоге (DEVELOPMENT_PLAN 6.3b; ARCHITECTURE §11.3): каждый опрос сообщений S30
продлевает метку в Valkey на VIEWING. Пока метка жива, `message.received` получателю не уходит.
Кэш — ускорение, не источник данных: Valkey недоступен — метки нет, уведомление уйдёт."""

from datetime import timedelta
from typing import Final
from uuid import UUID

from app.platform.cache.port import JsonCache
from app.platform.kernel.ids import UserId

VIEWING: Final = timedelta(seconds=20)
"""S30 опрашивает новые сообщения раз в 3–5 с: 20 с переживают пару пропущенных опросов."""


class CachePresence:
    def __init__(self, cache: JsonCache) -> None:
        self._cache = cache

    async def viewing(self, conversation_id: UUID, user_id: UserId) -> None:
        await self._cache.set(_key(conversation_id, user_id), 1, ttl=VIEWING)

    async def is_viewing(self, conversation_id: UUID, user_id: UserId) -> bool:
        return await self._cache.get(_key(conversation_id, user_id)) is not None


def _key(conversation_id: UUID, user_id: UserId) -> str:
    return f"messaging.viewing:v1:{conversation_id}:{user_id}"
