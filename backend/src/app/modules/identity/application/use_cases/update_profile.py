"""Правка своего профиля: имя, язык, город и намерение (PATCH /me, онбординг S02a–b).

Город проверяется через фасад geo (справочник — лист DAG, ARCHITECTURE §5.2 п. 4):
неизвестный — 422 `unknown_city`, «скоро» — 422 `city_not_available`. Повтор уже
выбранного города не проверяется: город мог стать «скоро» после выбора.
"""

from dataclasses import dataclass

from app.modules.geo.api import GeoApi
from app.modules.identity.application.ports import UserRepository
from app.modules.identity.domain.user import UserIntent
from app.modules.identity.errors import CityNotAvailableError, UnknownCityError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.localized import Locale


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateProfileCommand:
    actor_id: UserId
    display_name: str | None = None
    ui_locale: Locale | None = None
    home_city_id: CityId | None = None
    intent: UserIntent | None = None
    expected_version: int | None = None
    """Из If-Match; None — без сверки."""


class UpdateProfile:
    def __init__(self, uow: UnitOfWork, users: UserRepository, geo: GeoApi, clock: Clock) -> None:
        self._uow, self._users, self._geo, self._clock = uow, users, geo, clock

    async def __call__(self, cmd: UpdateProfileCommand) -> int:
        """Возвращает новую версию пользователя (ETag)."""
        async with self._uow:
            user = await self._users.get(cmd.actor_id)
            user.ensure_version(cmd.expected_version)
            if cmd.home_city_id is not None and cmd.home_city_id != user.home_city_id:
                await self._ensure_selectable(cmd.home_city_id)
            user.update_profile(
                display_name=cmd.display_name,
                ui_locale=cmd.ui_locale,
                home_city_id=cmd.home_city_id,
                intent=cmd.intent,
                now=self._clock.now(),
            )
            await self._users.save(user)
        return user.version

    async def _ensure_selectable(self, city_id: CityId) -> None:
        city = await self._geo.city(city_id)
        if city is None:
            raise UnknownCityError(city_id=city_id)
        if not city.is_active:
            raise CityNotAvailableError(city_id=city_id)
