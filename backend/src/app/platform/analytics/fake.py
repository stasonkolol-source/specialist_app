"""Аналитика без внешнего сервиса: dev без ключа PostHog (K32) и тесты.

События пишутся в лог (`analytics_event`), последние KEEP — в `captured` для тестов: в dev
регистрацию и онбординг видно в логе воркера. Список ограничен: без ключа K32 фейк работает
и в долгоживущем воркере stage и prod (до шага 3.4). События удалённых аккаунтов фейк, как и
PostHog, пропускает (deleted.py).
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Final

import structlog

from app.platform.analytics.deleted import skip_deleted
from app.platform.analytics.events import ensure_allowed
from app.platform.analytics.port import AnalyticsEvent, DeletedUsers

log = structlog.get_logger(__name__)


KEEP: Final = 1000


@dataclass
class LoggingAnalytics:
    captured: deque[AnalyticsEvent] = field(default_factory=lambda: deque(maxlen=KEEP))
    deleted: DeletedUsers | None = None

    async def capture(self, event: AnalyticsEvent) -> None:
        ensure_allowed(event)
        if await skip_deleted(self.deleted, event):
            return
        self.captured.append(event)
        log.info(
            "analytics_event",
            name=event.name,
            user_id=str(event.distinct_id),
            properties=dict(event.properties),
        )
