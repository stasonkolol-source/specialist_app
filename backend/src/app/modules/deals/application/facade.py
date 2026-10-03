"""Фасад deals (ADR-0020 §6): команды — в транзакции вызывающего модуля."""

from collections.abc import Collection
from uuid import UUID

from app.modules.deals.api import (
    AgreedDealIn,
    DealBrief,
    DealSummary,
    DisputeSummary,
    ProposedDealIn,
    SettleDisputeIn,
)
from app.modules.deals.application.dto import DealView, DisputeView
from app.modules.deals.application.ports import (
    DealQueries,
    DealRepository,
    DisputeQueries,
    DisputeRepository,
)
from app.modules.deals.domain.deal import (
    PROPOSAL_TTL,
    Deal,
    DealPriceType,
    DealRole,
    DealStatus,
    DealTerms,
)
from app.modules.deals.domain.dispute import Dispute, DisputeId, DisputeOutcome
from app.modules.deals.errors import (
    DealNotFoundError,
    DisputeNotFoundError,
    InvalidDealError,
    InvalidDisputeError,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, MediaId, UserId, new_id
from app.platform.kernel.pagination import Page, PageRequest


class DealsFacade:
    def __init__(
        self,
        uow: UnitOfWork,
        deals: DealRepository,
        queries: DealQueries,
        disputes: DisputeRepository,
        dispute_queries: DisputeQueries,
        clock: Clock,
    ) -> None:
        self._uow, self._deals, self._queries, self._clock = uow, deals, queries, clock
        self._disputes, self._dispute_queries = disputes, dispute_queries

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        deal = await self._queries.view(deal_id)
        return _brief(deal) if deal is not None else None

    async def deal_briefs(self, deal_ids: Collection[DealId]) -> dict[DealId, DealBrief]:
        return {deal.id: _brief(deal) for deal in await self._queries.views(deal_ids)}

    async def deal_for_response(self, response_id: UUID) -> DealBrief | None:
        deal_id = await self._queries.of_response(response_id)
        return await self.deal_brief(deal_id) if deal_id is not None else None

    async def deal_for(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        deal = await self._queries.view(deal_id)
        role = deal.role_of(viewer_id) if deal is not None else None
        if deal is None or role is None:
            raise DealNotFoundError(deal_id=deal_id)
        return _summary(deal, role)

    async def my_deals(self, viewer_id: UserId, page: PageRequest) -> Page[DealSummary]:
        found = await self._queries.mine(viewer_id, role=None, statuses=(), page=page)
        items = []
        for deal in found.items:
            role = deal.role_of(viewer_id)
            if role is not None:
                items.append(_summary(deal, role))
        return Page(items=tuple(items), next_cursor=found.next_cursor)

    async def deal_dispute(self, deal_id: DealId, viewer_id: UserId) -> DisputeSummary | None:
        deal = await self._queries.view(deal_id)
        if deal is None or deal.role_of(viewer_id) is None:
            raise DealNotFoundError(deal_id=deal_id)
        dispute = await self._dispute_queries.latest(deal_id)
        return dispute_summary(dispute) if dispute is not None else None

    async def dispute(self, dispute_id: UUID) -> DisputeSummary | None:
        dispute = await self._dispute_queries.view(DisputeId(dispute_id))
        return dispute_summary(dispute) if dispute is not None else None

    async def settle_dispute(self, data: SettleDisputeIn) -> DisputeSummary:
        self._uow.require_active()  # транзакция модерации: решение по кейсу и сделка вместе
        try:
            outcome = DisputeOutcome(data.outcome)
        except ValueError:
            raise InvalidDisputeError(field="outcome", reason="unknown") from None
        found = await self._dispute_queries.view(DisputeId(data.dispute_id))
        if found is None:
            raise DisputeNotFoundError(dispute_id=data.dispute_id)
        # порядок блокировок — сделка, затем спор: как у сторон (ответ, отзыв)
        deal = await self._deals.get_for_update(found.deal_id)
        dispute = await self._disputes.get_for_update(found.id)
        dispute.resolve(
            deal=deal,
            outcome=outcome,
            reason_code=data.reason_code,
            moderator_id=data.moderator_id,
            now=self._clock.now(),
        )
        await self._disputes.save(dispute)
        await self._deals.save(deal)
        return dispute_summary(dispute)

    async def disputing(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        return await self._dispute_queries.disputing(user_ids)

    async def dispute_evidence_held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        return await self._dispute_queries.evidence_held(media_ids)

    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        self._uow.require_active()  # транзакция jobs: отклик выбран и сделка создана вместе
        price_type = _price_type(data.price_type)
        deal = Deal.agree_from_response(
            deal_id=DealId(new_id()),
            client_id=data.client_id,
            performer_id=data.performer_id,
            profile_id=data.profile_id,
            job_id=data.job_id,
            response_id=data.response_id,
            terms=DealTerms(
                title=data.title,
                category_id=data.category_id,
                price_type=price_type,
                agreed_price=data.agreed_price,
                scheduled_at=data.scheduled_at,
            ),
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id

    async def propose(self, data: ProposedDealIn) -> DealId:
        self._uow.require_active()  # транзакция переписки: сделка и сообщение о ней вместе
        deal = Deal.propose(
            deal_id=DealId(new_id()),
            client_id=data.client_id,
            performer_id=data.performer_id,
            proposed_by=data.proposed_by,
            profile_id=data.profile_id,
            conversation_id=data.conversation_id,
            terms=DealTerms(
                title=data.title,
                category_id=data.category_id,
                price_type=_price_type(data.price_type) if data.price_type else None,
                agreed_price=data.agreed_price,
                scheduled_at=data.scheduled_at,
            ),
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id


def _price_type(value: str) -> DealPriceType:
    try:
        return DealPriceType(value)
    except ValueError:
        raise InvalidDealError(field="price_type", reason="unknown") from None


def dispute_summary(dispute: DisputeView | Dispute) -> DisputeSummary:
    """Спор строками перечислений — из чтения или из агрегата после решения."""
    return DisputeSummary(
        id=dispute.id,
        deal_id=dispute.deal_id,
        status=dispute.status.value,
        kind=dispute.kind.value,
        opened_by=dispute.opened_by,
        respondent_id=dispute.respondent_id,
        description=dispute.description,
        media_ids=dispute.media_ids,
        respond_by=dispute.respond_by,
        response=dispute.response,
        response_media_ids=dispute.response_media_ids,
        responded_at=dispute.responded_at,
        unanswered_at=dispute.unanswered_at,
        withdrawn_at=dispute.withdrawn_at,
        outcome=dispute.outcome.value if dispute.outcome is not None else None,
        reason_code=dispute.reason_code,
        resolved_by=dispute.resolved_by,
        resolved_at=dispute.resolved_at,
        created_at=dispute.created_at,
    )


def _brief(deal: DealView) -> DealBrief:
    return DealBrief(
        id=deal.id,
        client_id=deal.client_id,
        performer_id=deal.performer_id,
        title=deal.title,
        status=deal.status.value,
        origin=deal.origin.value,
        scheduled_at=deal.scheduled_at,
        price_type=deal.price_type.value if deal.price_type is not None else None,
        agreed_price=deal.agreed_price,
    )


def _summary(deal: DealView, role: DealRole) -> DealSummary:
    return DealSummary(
        id=deal.id,
        status=deal.status.value,
        origin=deal.origin.value,
        my_role=role.value,
        title=deal.title,
        price_type=deal.price_type.value if deal.price_type is not None else None,
        agreed_price=deal.agreed_price,
        scheduled_at=deal.scheduled_at,
        client_id=deal.client_id,
        performer_id=deal.performer_id,
        profile_id=deal.profile_id,
        job_id=deal.job_id,
        response_id=deal.response_id,
        conversation_id=deal.conversation_id,
        proposed_by=deal.proposed_by,
        agreed_at=deal.agreed_at,
        client_confirmed_at=deal.client_confirmed_at,
        performer_confirmed_at=deal.performer_confirmed_at,
        completed_at=deal.completed_at,
        cancelled_at=deal.cancelled_at,
        cancelled_by=deal.cancelled_by,
        cancel_reason=deal.cancel_reason.value if deal.cancel_reason is not None else None,
        created_at=deal.created_at,
        version=deal.version,
        proposal_expires_at=(
            deal.created_at + PROPOSAL_TTL if deal.status is DealStatus.PROPOSED else None
        ),
        category_id=deal.category_id,
    )
