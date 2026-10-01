"""Задачи pricing (ADR-0020 §3).

- `pricing.remove_profile_prices` — ProfileDeleted: аккаунт удалён — прайс удалён (§7.10).
"""

from dishka import FromDishka

from app.modules.pricing.application.ports import REMOVE_PROFILE_PRICES
from app.modules.pricing.application.use_cases.remove_profile_prices import (
    RemoveProfilePrices,
    RemoveProfilePricesCommand,
)
from app.platform.contracts.events.specialists import ProfileDeleted
from app.platform.queue.tasks import subscriber


@subscriber(ProfileDeleted, REMOVE_PROFILE_PRICES)
async def remove_profile_prices(
    event: ProfileDeleted, remove: FromDishka[RemoveProfilePrices]
) -> None:
    await remove(RemoveProfilePricesCommand(profile_id=event.profile_id))
