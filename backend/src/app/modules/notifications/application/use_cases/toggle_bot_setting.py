"""Переключить настройку из бота (`/settings`, DEVELOPMENT_PLAN 4.9): группа уведомлений в канале
«бот» или тихие часы — одним нажатием. Остальные настройки (приложение, время тихих часов,
дайджест) не меняются; служебную группу переключить нельзя."""

from dataclasses import dataclass, replace
from types import MappingProxyType

from app.modules.notifications.application.ports import NotificationQuery, SettingsRepository
from app.modules.notifications.domain.catalog import MANDATORY_GROUPS, Channel, EventGroup
from app.modules.notifications.domain.settings import NotificationSettings, Preferences
from app.modules.notifications.errors import MandatoryGroupError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ToggleBotSettingCommand:
    user_id: UserId
    group: EventGroup | None = None
    """Группа уведомлений в боте; None — тихие часы."""


class ToggleBotSetting:
    def __init__(
        self, uow: UnitOfWork, settings: SettingsRepository, query: NotificationQuery
    ) -> None:
        self._uow, self._settings, self._query = uow, settings, query

    async def __call__(self, cmd: ToggleBotSettingCommand) -> NotificationSettings:
        if cmd.group in MANDATORY_GROUPS:
            raise MandatoryGroupError(group=cmd.group.value)
        current = await self._query.settings(cmd.user_id)
        if cmd.group is None:
            quiet = current.quiet_hours
            changed = replace(current, quiet_hours=replace(quiet, enabled=not quiet.enabled))
        else:
            key = (cmd.group, Channel.TELEGRAM)
            choices = dict(current.preferences.choices)
            choices[key] = not current.preferences.allows(*key)
            changed = replace(current, preferences=Preferences(MappingProxyType(choices)))
        async with self._uow:
            await self._settings.save(cmd.user_id, changed)
        return changed
