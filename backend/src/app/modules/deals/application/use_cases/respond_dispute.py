"""Ответ второй стороны на спор (POST /deals/{id}/dispute/respond, S52; DEVELOPMENT_PLAN 6.1c):
текст и фото — один раз, в том числе после 48 ч, пока модератор не решил. Ответ и его фото
уходят в кейс модерации (DisputeAnswered). Не участник сделки — 404, открывший — 409."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository, DisputeRepository
from app.modules.deals.application.use_cases.open_dispute import check_evidence
from app.modules.deals.domain.dispute import DisputeId
from app.modules.deals.errors import DealNotFoundError
from app.modules.media.api import MediaApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RespondDisputeCommand:
    actor_id: UserId
    deal_id: DealId
    text: str
    media_ids: tuple[MediaId, ...] = ()


class RespondDispute:
    def __init__(
        self,
        uow: UnitOfWork,
        deals: DealRepository,
        disputes: DisputeRepository,
        media: MediaApi,
        clock: Clock,
    ) -> None:
        self._uow, self._deals, self._disputes = uow, deals, disputes
        self._media, self._clock = media, clock

    async def __call__(self, cmd: RespondDisputeCommand) -> DisputeId:
        await check_evidence(self._media, cmd.actor_id, cmd.media_ids)
        async with self._uow:
            # порядок блокировок — сделка, затем спор: как у открытия и решения модератора
            deal = await self._deals.get_for_update(cmd.deal_id)
            if deal.role_of(cmd.actor_id) is None:
                raise DealNotFoundError(deal_id=cmd.deal_id)
            dispute = await self._disputes.active_for_update(cmd.deal_id)
            dispute.respond(
                actor_id=cmd.actor_id,
                text=cmd.text,
                media_ids=cmd.media_ids,
                now=self._clock.now(),
            )
            await self._disputes.save(dispute)
        return dispute.id
