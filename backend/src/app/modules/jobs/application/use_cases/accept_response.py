"""Выбрать исполнителя (POST /responses/{id}/accept, S25; DEVELOPMENT_PLAN 6.1a): отклик принят,
остальные — «не выбран», заявка «в работе», и в той же транзакции фасад deals создаёт сделку
`agreed` (ADR-0020 §4): сбой сделки откатывает выбор. Отклик того, с кем у клиента блокировка
(4.7), — как невидимый: 404."""

from dataclasses import dataclass

from app.modules.deals.api import AgreedDealIn, DealsApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.dto import AcceptedResponse
from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.errors import ResponseNotFoundError
from app.platform.contracts.events.jobs import ResponseAccepted
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptResponseCommand:
    actor_id: UserId
    response_id: ResponseId


class AcceptResponse:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        deals: DealsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._deals = uow, jobs, queries, deals
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: AcceptResponseCommand) -> AcceptedResponse:
        job_id = await self._queries.job_of_response(cmd.response_id)
        if job_id is None:
            raise ResponseNotFoundError(response_id=cmd.response_id)
        now = self._clock.now()
        async with self._uow:
            job = await self._jobs.get_for_update(job_id)
            response = job.accept_response(cmd.response_id, client_id=cmd.actor_id, now=now)
            if await self._identity.blocks_with(cmd.actor_id, [response.performer_id]):
                raise ResponseNotFoundError(response_id=cmd.response_id)
            offer = response.offer
            deal_id = await self._deals.create_agreed(
                AgreedDealIn(
                    client_id=job.client_id,
                    performer_id=response.performer_id,
                    profile_id=response.profile_id,
                    job_id=job.id,
                    response_id=response.id,
                    title=job.content.title,
                    category_id=job.content.category_id,
                    price_type=offer.price_type.value,
                    agreed_price=offer.price_amount,
                    scheduled_at=job.content.preferred_from,
                )
            )
            await self._jobs.save(job)
            self._uow.add_event(
                ResponseAccepted(
                    job_id=job.id,
                    response_id=response.id,
                    performer_id=response.performer_id,
                    client_id=job.client_id,
                    deal_id=deal_id,
                    occurred_at=now,
                )
            )
        return AcceptedResponse(job_id=job_id, deal_id=deal_id)
