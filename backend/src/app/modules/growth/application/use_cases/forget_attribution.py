"""Удалённый аккаунт (подписчик UserDeleted; ARCHITECTURE §7.10): первое касание и код
приглашения больше не нужны — атрибуция и свой код `_r` (7.4) удалены. Повтор задачи ничего не
меняет."""

from dataclasses import dataclass

from app.modules.growth.application.ports import AttributionRepository, ReferralCodes
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetAttributionCommand:
    user_id: UserId


class ForgetAttribution:
    def __init__(
        self, uow: UnitOfWork, attributions: AttributionRepository, codes: ReferralCodes
    ) -> None:
        self._uow, self._attributions, self._codes = uow, attributions, codes

    async def __call__(self, cmd: ForgetAttributionCommand) -> None:
        async with self._uow:
            await self._attributions.forget(cmd.user_id)
            await self._codes.forget(cmd.user_id)
