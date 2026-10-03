"""Репозитории сделок и споров (ADR-0020 §5): переходы статусов сделки — в
`deals.status_history` при каждом сохранении. Второй выбор того же отклика упирается в
`uq_deals_response_id`."""

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deals.domain.deal import CANCELLABLE, Deal, DealTerms
from app.modules.deals.domain.dispute import ACTIVE as ACTIVE_DISPUTES
from app.modules.deals.domain.dispute import Dispute, DisputeId
from app.modules.deals.errors import DealNotFoundError, DisputeNotFoundError
from app.modules.deals.infrastructure.models import DealRow, DisputeRow, StatusHistoryRow
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, DealId, MediaId, UserId


class SqlDealRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, deal: Deal) -> None:
        self._uow.require_active()
        row = DealRow(id=deal.id, version=deal.version, created_at=deal.created_at)
        _apply(deal, row)
        self._session.add(row)
        await self._session.flush()
        self._add_history(deal)
        await self._session.flush()
        self._uow.track(deal)

    async def get_for_update(self, deal_id: DealId) -> Deal:
        self._uow.require_active()
        stmt = (
            select(DealRow)
            .where(DealRow.id == deal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise DealNotFoundError(deal_id=deal_id)
        deal = _to_domain(row)
        self._uow.track(deal)
        return deal

    async def save(self, deal: Deal) -> None:
        self._uow.require_active()
        row = await self._session.get(DealRow, deal.id)
        if row is None:
            raise DealNotFoundError(deal_id=deal.id)
        check_loaded_version(entity="deal", loaded=row.version, expected=deal.version)
        _apply(deal, row)
        row.version = deal.version + 1
        await self._session.flush()
        self._add_history(deal)
        await self._session.flush()
        deal.mark_persisted(version=row.version)
        self._uow.track(deal)

    async def cancellable_of(self, user_id: UserId) -> list[DealId]:
        self._uow.require_active()
        stmt = select(DealRow.id).where(
            or_(DealRow.client_id == user_id, DealRow.performer_id == user_id),
            DealRow.status.in_([status.value for status in CANCELLABLE]),
        )
        return [DealId(value) for value in (await self._session.scalars(stmt)).all()]

    def _add_history(self, deal: Deal) -> None:
        self._session.add_all(
            StatusHistoryRow(
                deal_id=deal.id,
                from_status=change.from_.value if change.from_ is not None else None,
                to_status=change.to.value,
                actor_id=change.actor_id,
                actor_kind=change.actor_kind,
                reason=change.reason,
                created_at=change.at,
            )
            for change in deal.pull_history()
        )


def _to_domain(row: DealRow) -> Deal:
    return Deal(
        id=DealId(row.id),
        client_id=UserId(row.client_id),
        performer_id=UserId(row.performer_id),
        origin=row.origin,
        terms=DealTerms(
            title=row.title_snapshot,
            category_id=CategoryId(row.category_id) if row.category_id is not None else None,
            price_type=row.price_type,
            agreed_price=row.agreed_price,
            scheduled_at=row.scheduled_at,
        ),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        profile_id=row.profile_id,
        job_id=row.job_id,
        response_id=row.response_id,
        conversation_id=row.conversation_id,
        proposed_by=UserId(row.proposed_by) if row.proposed_by is not None else None,
        agreed_at=row.agreed_at,
        client_confirmed_at=row.client_confirmed_at,
        performer_confirmed_at=row.performer_confirmed_at,
        completed_at=row.completed_at,
        cancelled_at=row.cancelled_at,
        cancelled_by=UserId(row.cancelled_by) if row.cancelled_by is not None else None,
        cancel_reason=row.cancel_reason,
        reminded_at=row.reminded_at,
        completion_prompted_at=row.completion_prompted_at,
        version=row.version,
    )


def _apply(deal: Deal, row: DealRow) -> None:
    terms = deal.terms
    row.client_id = deal.client_id
    row.performer_id = deal.performer_id
    row.profile_id = deal.profile_id
    row.origin = deal.origin
    row.job_id = deal.job_id
    row.response_id = deal.response_id
    row.conversation_id = deal.conversation_id
    row.title_snapshot = terms.title
    row.category_id = terms.category_id
    row.status = deal.status
    row.proposed_by = deal.proposed_by
    row.price_type = terms.price_type
    row.agreed_price = terms.agreed_price
    row.scheduled_at = terms.scheduled_at
    row.agreed_at = deal.agreed_at
    row.client_confirmed_at = deal.client_confirmed_at
    row.performer_confirmed_at = deal.performer_confirmed_at
    row.completed_at = deal.completed_at
    row.cancelled_at = deal.cancelled_at
    row.cancelled_by = deal.cancelled_by
    row.cancel_reason = deal.cancel_reason
    row.reminded_at = deal.reminded_at
    row.completion_prompted_at = deal.completion_prompted_at
    row.updated_at = deal.updated_at


class SqlDisputeRepository:
    """Споры (6.1c): один идущий на сделку держит `uq_disputes_deal_id_active`, а use case
    берёт спор после блокировки строки сделки — второй запрос ждёт и видит `disputed`."""

    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, dispute: Dispute) -> None:
        self._uow.require_active()
        row = DisputeRow(id=dispute.id, version=dispute.version, created_at=dispute.created_at)
        _apply_dispute(dispute, row)
        self._session.add(row)
        await self._session.flush()
        self._uow.track(dispute)

    async def active_for_update(self, deal_id: DealId) -> Dispute:
        dispute = await self._locked(
            DisputeRow.deal_id == deal_id,
            DisputeRow.status.in_([status.value for status in ACTIVE_DISPUTES]),
        )
        if dispute is None:
            raise DisputeNotFoundError(deal_id=deal_id)
        return dispute

    async def get_for_update(self, dispute_id: DisputeId) -> Dispute:
        dispute = await self._locked(DisputeRow.id == dispute_id)
        if dispute is None:
            raise DisputeNotFoundError(dispute_id=dispute_id)
        return dispute

    async def save(self, dispute: Dispute) -> None:
        self._uow.require_active()
        row = await self._session.get(DisputeRow, dispute.id)
        if row is None:
            raise DisputeNotFoundError(dispute_id=dispute.id)
        check_loaded_version(entity="dispute", loaded=row.version, expected=dispute.version)
        _apply_dispute(dispute, row)
        row.version = dispute.version + 1
        await self._session.flush()
        dispute.mark_persisted(version=row.version)
        self._uow.track(dispute)

    async def _locked(self, *conditions: ColumnElement[bool]) -> Dispute | None:
        self._uow.require_active()
        stmt = (
            select(DisputeRow)
            .where(*conditions)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        dispute = _dispute(row)
        self._uow.track(dispute)
        return dispute


def _dispute(row: DisputeRow) -> Dispute:
    return Dispute(
        id=DisputeId(row.id),
        deal_id=DealId(row.deal_id),
        opened_by=UserId(row.opened_by),
        respondent_id=UserId(row.respondent_id),
        kind=row.kind,
        description=row.description,
        media_ids=tuple(MediaId(media_id) for media_id in row.media_ids),
        respond_by=row.respond_by,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        response=row.response,
        response_media_ids=tuple(MediaId(media_id) for media_id in row.response_media_ids),
        responded_at=row.responded_at,
        unanswered_at=row.unanswered_at,
        withdrawn_at=row.withdrawn_at,
        outcome=row.outcome,
        reason_code=row.reason_code,
        resolved_by=UserId(row.resolved_by) if row.resolved_by is not None else None,
        resolved_at=row.resolved_at,
        version=row.version,
    )


def _apply_dispute(dispute: Dispute, row: DisputeRow) -> None:
    row.deal_id = dispute.deal_id
    row.opened_by = dispute.opened_by
    row.respondent_id = dispute.respondent_id
    row.kind = dispute.kind
    row.description = dispute.description
    row.media_ids = list(dispute.media_ids)
    row.respond_by = dispute.respond_by
    row.status = dispute.status
    row.response = dispute.response
    row.response_media_ids = list(dispute.response_media_ids)
    row.responded_at = dispute.responded_at
    row.unanswered_at = dispute.unanswered_at
    row.withdrawn_at = dispute.withdrawn_at
    row.outcome = dispute.outcome
    row.reason_code = dispute.reason_code
    row.resolved_by = dispute.resolved_by
    row.resolved_at = dispute.resolved_at
    row.updated_at = dispute.updated_at
