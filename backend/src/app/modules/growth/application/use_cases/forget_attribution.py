"""Удалённый аккаунт (подписчик UserDeleted; ARCHITECTURE §7.10): первое касание и код
приглашения больше не нужны — атрибуция удалена. Повтор задачи ничего не меняет."""

from dataclasses import dataclass

from app.modules.growth.application.ports import AttributionRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetAttributionCommand:
    user_id: UserId


class ForgetAttribution:
    def __init__(self, uow: UnitOfWork, attributions: AttributionRepository) -> None:
        self._uow, self._attributions = uow, attributions

    async def __call__(self, cmd: ForgetAttributionCommand) -> None:
        async with self._uow:
            await self._attributions.forget(cmd.user_id)
