"""Репозиторий сделок (ADR-0020 §5): переходы статусов — в `deals.status_history` при каждом
сохранении. Второй выбор того же отклика упирается в `uq_deals_response_id`."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deals.domain.deal import Deal, DealTerms
from app.modules.deals.errors import DealNotFoundError
from app.modules.deals.infrastructure.models import DealRow, StatusHistoryRow
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, DealId, UserId


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
    row.updated_at = deal.updated_at
