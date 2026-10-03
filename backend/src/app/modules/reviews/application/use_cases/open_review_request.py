"""Попросить отзыв (задача `reviews.open_request` на DealCompleted; DEVELOPMENT_PLAN 7.2): клиент
завершённой сделки получает `review.request`; напоминания ставит `reviews.reminders`. Повтор
задачи второй просьбы не пошлёт."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.reviews.application.ports import ReviewRequests
from app.modules.reviews.domain.request import RequestStage
from app.platform.contracts.events.reviews import ReviewRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenReviewRequestCommand:
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    completed_at: datetime


class OpenReviewRequest:
    def __init__(self, uow: UnitOfWork, requests: ReviewRequests) -> None:
        self._uow, self._requests = uow, requests

    async def __call__(self, cmd: OpenReviewRequestCommand) -> bool:
        """True — просьба новая, `review.request` уйдёт."""
        async with self._uow:
            opened = await self._requests.open(
                deal_id=cmd.deal_id,
                client_id=cmd.client_id,
                performer_id=cmd.performer_id,
                completed_at=cmd.completed_at,
            )
            if opened:
                self._uow.add_event(
                    ReviewRequested(
                        deal_id=cmd.deal_id,
                        client_id=cmd.client_id,
                        performer_id=cmd.performer_id,
                        stage=RequestStage.FIRST.value,
                        occurred_at=cmd.completed_at,
                    )
                )
        return opened
