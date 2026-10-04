"""Час подборки заявок по подпискам (DEVELOPMENT_PLAN 5.7): реализация jobs.api.DigestSchedule.

Час дайджеста — в настройках уведомлений (`notifications.user_settings.digest_hour`, по Белграду;
кто не менял — 09:00). jobs спрашивает, кому подборка положена в этот час, не зная о настройках.
"""

from collections.abc import Collection
from datetime import datetime

from app.modules.notifications.application.ports import NotificationQuery
from app.modules.notifications.domain.settings import DIGEST_HOUR, TIMEZONE
from app.platform.kernel.ids import UserId


class SettingsDigestSchedule:
    def __init__(self, query: NotificationQuery) -> None:
        self._query = query

    async def due(self, user_ids: Collection[UserId], at: datetime) -> frozenset[UserId]:
        hour = at.astimezone(TIMEZONE).hour
        hours = await self._query.digest_hours(user_ids)
        return frozenset(user_id for user_id in user_ids if hours.get(user_id, DIGEST_HOUR) == hour)
