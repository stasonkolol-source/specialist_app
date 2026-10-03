"""Прогрев процесса web при старте (перф-аудит 2026-10).

После рестарта первые запросы платили за всё, что создаётся лениво: соединения с PostgreSQL
(TCP и аутентификация), чтение client-config, пул Procrastinate, клиенты boto3, соединение с
Valkey — в dev-логе 1,2–1,4 с на первом запросе. Lifespan делает это до приёма запросов.
Прогрев — не условие старта: недоступная зависимость пишет предупреждение, а соединение
откроется по запросу, как раньше.
"""

from typing import Final

import procrastinate
import structlog
from dishka import AsyncContainer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.config.cache import ClientConfigCache
from app.platform.db.engine import warm_up
from app.platform.storage.port import StoragePort

log = structlog.get_logger(__name__)

WARM_CONNECTIONS: Final = 2
"""Соединений с базой при старте: на первые параллельные запросы запуска Mini App."""


async def warm_up_web(container: AsyncContainer) -> None:
    try:
        await warm_up(await container.get(AsyncEngine), WARM_CONNECTIONS)
        await container.get(procrastinate.App)  # пул Procrastinate открывается при создании
    except (SQLAlchemyError, OSError) as exc:
        log.warning("warm_up_db_failed", error=type(exc).__name__)
    await (await container.get(ClientConfigCache)).get()  # сбой базы кэш переживает сам
    try:
        await (await container.get(Redis)).ping()  # type: ignore[misc]  # redis-py: Awaitable | bool
    except (RedisError, OSError) as exc:
        log.warning("warm_up_valkey_failed", error=type(exc).__name__)
    try:
        await container.get(StoragePort)  # клиенты boto3 создаются долго
    except Exception as exc:  # noqa: BLE001 — без S3 web работает, ошибка будет в запросе к медиа
        log.warning("warm_up_storage_failed", error=type(exc).__name__)
