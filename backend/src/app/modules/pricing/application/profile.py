"""Профиль текущего пользователя для команд прайса: прайс живёт в профиле исполнителя."""

from uuid import UUID

from app.modules.pricing.errors import NoProfileError
from app.modules.specialists.api import SpecialistsApi
from app.platform.contracts.events.pricing import PriceListChanged
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


async def profile_id_of(specialists: SpecialistsApi, user_id: UserId) -> UUID:
    profile = await specialists.profile_of(user_id)
    if profile is None:
        raise NoProfileError(user_id=user_id)
    return profile.id


def price_list_changed(uow: UnitOfWork, profile_id: UUID, user_id: UserId, clock: Clock) -> None:
    uow.add_event(PriceListChanged(profile_id=profile_id, user_id=user_id, occurred_at=clock.now()))
