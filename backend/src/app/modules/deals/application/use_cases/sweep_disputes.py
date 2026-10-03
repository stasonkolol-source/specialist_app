"""Срок ответа на спор (periodic `deals.dispute_response_sla`, каждые 30 минут; DEVELOPMENT_PLAN
6.1c, ARCHITECTURE §12.3): вторая сторона молчит 48 ч — спор «нет ответа» (DisputeUnanswered),
и модерация помечает кейс. Каждый спор — своей короткой транзакцией, за проход — не больше
`limit`, как у сроков сделок."""

from dataclasses import dataclass
from typing import Final

from app.modules.deals.application.ports import DisputeQueries, DisputeRepository
from app.modules.deals.errors import DisputeNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

BATCH: Final = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class SweepDisputesCommand:
    limit: int = BATCH


class SweepDisputes:
    def __init__(
        self,
        uow: UnitOfWork,
        disputes: DisputeRepository,
        queries: DisputeQueries,
        clock: Clock,
    ) -> None:
        self._uow, self._disputes, self._queries, self._clock = uow, disputes, queries, clock

    async def __call__(self, cmd: SweepDisputesCommand) -> int:
        """Сколько споров помечено «нет ответа»."""
        now = self._clock.now()
        marked = 0
        for dispute_id in await self._queries.unanswered_due(now, limit=cmd.limit):
            async with self._uow:
                try:
                    dispute = await self._disputes.get_for_update(dispute_id)
                except DisputeNotFoundError:
                    continue
                if dispute.mark_unanswered(now=now):  # ответ успел раньше — уже не пора
                    await self._disputes.save(dispute)
                    marked += 1
        return marked
