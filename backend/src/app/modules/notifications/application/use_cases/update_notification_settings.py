"""Сохранить настройки уведомлений (`PUT /me/notification-settings`, S43).

Настройки заменяются целиком: группы × каналы, тихие часы, час дайджеста. Служебную
группу выключить нельзя — 422 `notification_group_mandatory`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.modules.notifications.application.dto import SettingsView
from app.modules.notifications.application.ports import NotificationQuery, SettingsRepository
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.domain.settings import (
    NotificationSettings,
    Preferences,
    QuietHours,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateNotificationSettingsCommand:
    user_id: UserId
    choices: Mapping[tuple[EventGroup, Channel], bool]
    quiet_hours: QuietHours
    digest_hour: int


class UpdateNotificationSettings:
    def __init__(
        self, uow: UnitOfWork, settings: SettingsRepository, query: NotificationQuery
    ) -> None:
        self._uow, self._settings, self._query = uow, settings, query

    async def __call__(self, cmd: UpdateNotificationSettingsCommand) -> SettingsView:
        settings = NotificationSettings(
            preferences=Preferences(MappingProxyType(dict(cmd.choices))),
            quiet_hours=cmd.quiet_hours,
            digest_hour=cmd.digest_hour,
        )
        async with self._uow:
            await self._settings.save(cmd.user_id, settings)
        return SettingsView(
            settings=settings, telegram=await self._query.telegram_channel(cmd.user_id)
        )
