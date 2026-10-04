"""Сохранить настройки уведомлений (`PUT /me/notification-settings`, S43).

Настройки заменяются целиком: группы × каналы, тихие часы, час дайджеста. Служебную
группу выключить нельзя — 422 `notification_group_mandatory`. Включение группы
`goods_launch` («Сообщить о запуске» на S58, 7.5) — запись в лист ожидания раздела «Вещи»:
`GoodsWaitlistJoined` для аналитики. Прежние настройки читаются под блокировкой: два
параллельных нажатия не дадут двух событий.
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
from app.platform.contracts.events.notifications import GoodsWaitlistJoined
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateNotificationSettingsCommand:
    user_id: UserId
    choices: Mapping[tuple[EventGroup, Channel], bool]
    quiet_hours: QuietHours
    digest_hour: int


def _waits_for_goods(preferences: Preferences) -> bool:
    """Подписан на запуск «Вещей» хотя бы в одном канале."""
    return any(preferences.allows(EventGroup.GOODS_LAUNCH, channel) for channel in Channel)


class UpdateNotificationSettings:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: SettingsRepository,
        query: NotificationQuery,
        clock: Clock,
    ) -> None:
        self._uow, self._settings, self._query, self._clock = uow, settings, query, clock

    async def __call__(self, cmd: UpdateNotificationSettingsCommand) -> SettingsView:
        settings = NotificationSettings(
            preferences=Preferences(MappingProxyType(dict(cmd.choices))),
            quiet_hours=cmd.quiet_hours,
            digest_hour=cmd.digest_hour,
        )
        joins = _waits_for_goods(settings.preferences)
        async with self._uow:
            if joins:
                await self._settings.lock(cmd.user_id)
                joins = not _waits_for_goods((await self._settings.load(cmd.user_id)).preferences)
            await self._settings.save(cmd.user_id, settings)
            if joins:
                # канал — чтение без блокировки: только свойство события, не условие записи
                channel = await self._query.telegram_channel(cmd.user_id)
                self._uow.add_event(
                    GoodsWaitlistJoined(
                        user_id=cmd.user_id,
                        bot_writable=channel is not None and channel.writable,
                        occurred_at=self._clock.now(),
                    )
                )
        return SettingsView(
            settings=settings, telegram=await self._query.telegram_channel(cmd.user_id)
        )
