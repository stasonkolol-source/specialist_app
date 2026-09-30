"""Лаг очередей (ARCHITECTURE §12.4): сколько ждёт самая старая готовая к запуску задача.

Ждёт задача с момента, когда попала в `todo` (постановка, повтор после ошибки, ручной
повтор), а отложенная — с `scheduled_at`: отложенная до утра не опаздывает ночью.
"""

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LAG_ALERT_SECONDS: Mapping[str, float] = MappingProxyType(
    {"notifications": 120.0, "default": 600.0, "media": 600.0}
)
"""Порог алерта по очереди (§12.4): уведомления опаздывают заметнее всего."""

_LAGS = text(
    """
    SELECT j.queue_name AS queue,
           EXTRACT(EPOCH FROM now() - MIN(GREATEST(e.ready_at, COALESCE(j.scheduled_at, e.ready_at)
           ))) AS lag
    FROM procrastinate_jobs j
    JOIN LATERAL (
        SELECT max(at) AS ready_at FROM procrastinate_events
        WHERE job_id = j.id AND type IN ('deferred', 'deferred_for_retry', 'retried')
    ) e ON true
    WHERE j.status = 'todo' AND (j.scheduled_at IS NULL OR j.scheduled_at <= now())
    GROUP BY j.queue_name
    """
)


async def queue_lags(session: AsyncSession) -> dict[str, float]:
    """Лаг по очередям, где есть готовые к запуску задачи; пустая очередь — нет ключа."""
    rows = (await session.execute(_LAGS)).all()
    return {row.queue: max(0.0, float(row.lag)) for row in rows if row.lag is not None}
