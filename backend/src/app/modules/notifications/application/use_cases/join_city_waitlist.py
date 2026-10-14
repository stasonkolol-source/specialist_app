"""Лист ожидания города «скоро» (`POST /me/city-waitlist`, S02a).

Город со статусом «скоро» (geo, `active: false`) виден на S02a, но не выбирается. «Сообщить о
запуске» включает opt-in группу `city_launch` в обоих каналах — тот же механизм, что у «Вещей»
(S58, `goods_launch`): запись — в настройках уведомлений, своей таблицы нет. О запуске напишет
рассылка из админки этой группе; отписка — переключатель S43. Переход группы из «выключено» во
«включено» — событие CityWaitlistJoined с городом для аналитики (`city_waitlist_joined`).
Повторное нажатие ничего не меняет и события не повторяет. Настройки читаются под блокировкой:
два параллельных нажатия не дадут двух событий.
"""

from dataclasses import dataclass, replace
from types import MappingProxyType

from app.modules.geo.api import GeoApi
from app.modules.notifications.application.dto import SettingsView
from app.modules.notifications.application.ports import NotificationQuery, SettingsRepository
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.domain.settings import Preferences
from app.modules.notifications.errors import CityNotUpcomingError
from app.platform.contracts.events.notifications import CityWaitlistJoined
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CityId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JoinCityWaitlistCommand:
    user_id: UserId
    city_id: CityId


def waits_for_city(preferences: Preferences) -> bool:
    """Подписан на запуск города хотя бы в одном канале."""
    return any(preferences.allows(EventGroup.CITY_LAUNCH, channel) for channel in Channel)


class JoinCityWaitlist:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: SettingsRepository,
        query: NotificationQuery,
        geo: GeoApi,
        clock: Clock,
    ) -> None:
        self._uow, self._settings, self._query = uow, settings, query
        self._geo, self._clock = geo, clock

    async def __call__(self, cmd: JoinCityWaitlistCommand) -> SettingsView:
        city = await self._geo.city(cmd.city_id)
        if city is None or city.is_active:
            raise CityNotUpcomingError(city_id=cmd.city_id)
        async with self._uow:
            await self._settings.lock(cmd.user_id)
            current = await self._settings.load(cmd.user_id)
            if not waits_for_city(current.preferences):
                choices = dict(current.preferences.choices)
                choices.update({(EventGroup.CITY_LAUNCH, channel): True for channel in Channel})
                current = replace(current, preferences=Preferences(MappingProxyType(choices)))
                await self._settings.save(cmd.user_id, current)
                # канал — чтение без блокировки: только свойство события, не условие записи
                channel = await self._query.telegram_channel(cmd.user_id)
                self._uow.add_event(
                    CityWaitlistJoined(
                        user_id=cmd.user_id,
                        city_id=cmd.city_id,
                        bot_writable=channel is not None and channel.writable,
                        occurred_at=self._clock.now(),
                    )
                )
        return SettingsView(
            settings=current, telegram=await self._query.telegram_channel(cmd.user_id)
        )
