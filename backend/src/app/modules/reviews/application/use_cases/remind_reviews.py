"""Напомнить об отзыве (periodic `reviews.reminders`, раз в час; ARCHITECTURE §12.3): через сутки
после завершения и за 2 дня до конца окна в 14 дней — пока клиент не оставил отзыв. Порцией;
строки под `SKIP LOCKED`, два воркера одно напоминание не пошлют."""

from dataclasses import dataclass
from typing import Final

from app.modules.reviews.application.ports import ReviewRequests
from app.modules.reviews.domain.request import due_stage
from app.platform.contracts.events.reviews import ReviewRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

BATCH: Final = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class RemindReviewsCommand:
    limit: int = BATCH


class RemindReviews:
    def __init__(self, uow: UnitOfWork, requests: ReviewRequests, clock: Clock) -> None:
        self._uow, self._requests, self._clock = uow, requests, clock

    async def __call__(self, cmd: RemindReviewsCommand) -> int:
        """Сколько напоминаний поставлено."""
        now = self._clock.now()
        sent = 0
        async with self._uow:
            for request in await self._requests.awaiting(now, limit=cmd.limit):
                stage = due_stage(
                    completed_at=request.completed_at,
                    reminded_at=request.reminded_at,
                    last_call_at=request.last_call_at,
                    now=now,
                )
                if stage is None:
                    continue
                await self._requests.mark(request.deal_id, stage, now)
                self._uow.add_event(
                    ReviewRequested(
                        deal_id=request.deal_id,
                        client_id=request.client_id,
                        performer_id=request.performer_id,
                        stage=stage.value,
                        occurred_at=now,
                    )
                )
                sent += 1
        return sent
