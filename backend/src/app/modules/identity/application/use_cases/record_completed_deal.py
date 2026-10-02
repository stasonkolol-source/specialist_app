"""Сделка завершена (подписчик DealCompleted; DEVELOPMENT_PLAN 6.1a, ADR-0016 §2): обеим
сторонам — факт завершённой сделки и пересчёт уровня доверия: третья сделка поднимает до 2.
Повтор задачи ничего не меняет; удалённого пользователя не трогаем."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.application.ports import CompletedDeals, UserRepository
from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.domain.user import UserStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordCompletedDealCommand:
    deal_id: DealId
    user_ids: Sequence[UserId]
    """Стороны сделки: клиент и исполнитель."""
    completed_at: datetime


class RecordCompletedDeal:
    def __init__(
        self,
        uow: UnitOfWork,
        deals: CompletedDeals,
        users: UserRepository,
        trust: TrustRecalculation,
        clock: Clock,
    ) -> None:
        self._uow, self._deals, self._users = uow, deals, users
        self._trust, self._clock = trust, clock

    async def __call__(self, cmd: RecordCompletedDealCommand) -> int:
        """Скольким сторонам записан новый факт."""
        recorded = 0
        async with self._uow:
            for user_id in cmd.user_ids:
                if not await self._deals.record(user_id, cmd.deal_id, cmd.completed_at):
                    continue
                recorded += 1
                user = await self._users.get_for_update(user_id)
                if user.status is UserStatus.DELETED:
                    continue
                await self._trust.apply(user, now=self._clock.now())
                await self._users.save(user)
        return recorded
