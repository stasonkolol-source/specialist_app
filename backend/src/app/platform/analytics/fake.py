"""Аналитика без внешнего сервиса: dev без ключа PostHog (K32) и тесты.

События пишутся в лог (`analytics_event`) и копятся в `captured`: в dev регистрацию и
онбординг видно в логе воркера, тест проверяет список.
"""

from dataclasses import dataclass, field

import structlog

from app.platform.analytics.port import AnalyticsEvent

log = structlog.get_logger(__name__)


@dataclass
class LoggingAnalytics:
    captured: list[AnalyticsEvent] = field(default_factory=list)

    async def capture(self, event: AnalyticsEvent) -> None:
        self.captured.append(event)
        log.info(
            "analytics_event",
            name=event.name,
            user_id=str(event.distinct_id),
            properties=dict(event.properties),
        )
