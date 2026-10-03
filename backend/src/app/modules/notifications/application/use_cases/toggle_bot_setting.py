"""Переключить настройку из бота (`/settings`, DEVELOPMENT_PLAN 4.9): группа уведомлений в канале
«бот» или тихие часы — одним нажатием. Остальные настройки (приложение, время тихих часов,
дайджест) не меняются; служебную группу переключить нельзя.

Чтение и запись — в одной транзакции под блокировкой настроек пользователя: Telegram присылает
каждое нажатие отдельным апдейтом, и бот обрабатывает их параллельно. Без блокировки двойное
нажатие прочитало бы одно и то же и записало бы одно и то же — второе нажатие потерялось бы.
"""

from dataclasses import dataclass, replace
from types import MappingProxyType

from app.modules.notifications.application.ports import SettingsRepository
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
    def __init__(self, uow: UnitOfWork, settings: SettingsRepository) -> None:
        self._uow, self._settings = uow, settings

    async def __call__(self, cmd: ToggleBotSettingCommand) -> NotificationSettings:
        if cmd.group in MANDATORY_GROUPS:
            raise MandatoryGroupError(group=cmd.group.value)
        async with self._uow:
            await self._settings.lock(cmd.user_id)
            current = await self._settings.load(cmd.user_id)
            if cmd.group is None:
                quiet = current.quiet_hours
                changed = replace(current, quiet_hours=replace(quiet, enabled=not quiet.enabled))
            else:
                key = (cmd.group, Channel.TELEGRAM)
                choices = dict(current.preferences.choices)
                choices[key] = not current.preferences.allows(*key)
                changed = replace(current, preferences=Preferences(MappingProxyType(choices)))
            await self._settings.save(cmd.user_id, changed)
        return changed
