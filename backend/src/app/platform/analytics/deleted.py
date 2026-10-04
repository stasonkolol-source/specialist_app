"""Аналитика молчит об удалённых аккаунтах (DEVELOPMENT_PLAN 2.12b, ARCHITECTURE §7.10).

После UserDeleted другие модули ещё публикуют события с id удалённого: сделка отменена
(`account_deleted`, по событию на каждую сторону), заявки закрыты; задача capture, поставленная
до удаления, могла ждать повтора. PostHog удаляет только события, пойманные до запроса
`forget_person`, а новое событие заводит персону заново. Поэтому адаптер перед отправкой
спрашивает, не удалён ли пользователь, — по `identity.users.deleted_at`, как отчёты
liquidity.py: признак ставится в той же транзакции, что и UserDeleted, и любая задача после
неё его видит. Порт с реализацией в identity здесь не годится: адаптер аналитики живёт весь
процесс (Scope.APP) и не берёт сессию запроса.
"""

from collections.abc import Collection
from uuid import UUID

import structlog
from sqlalchemy import Uuid, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.platform.analytics.port import AnalyticsEvent, DeletedUsers

log = structlog.get_logger(__name__)

_USERS = table("users", column("id", Uuid()), column("deleted_at"), schema="identity")


class SqlDeletedUsers:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def deleted(self, user_ids: Collection[UUID]) -> frozenset[UUID]:
        if not user_ids:
            return frozenset()
        stmt = select(_USERS.c.id).where(
            _USERS.c.id.in_(list(user_ids)), _USERS.c.deleted_at.is_not(None)
        )
        async with self._maker() as session:
            return frozenset(await session.scalars(stmt))


async def skip_deleted(deleted: DeletedUsers | None, event: AnalyticsEvent) -> bool:
    """Событие удалённого пользователя не отправляем; без проверки (юнит-тесты) — отправляем."""
    if deleted is None or event.distinct_id not in await deleted.deleted((event.distinct_id,)):
        return False
    log.info("analytics_event_skipped", name=event.name, reason="user_deleted")
    return True
