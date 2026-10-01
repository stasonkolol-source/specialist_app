"""Прайс профиля в PostgreSQL: позиции — простые записи профиля (ADR-0020 §5)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.domain.service import Service, ServiceId
from app.modules.pricing.errors import ServiceNotFoundError
from app.modules.pricing.infrastructure.models import ServiceRow
from app.modules.specialists.api import PriceSummary
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId


class SqlServiceRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def list_for_update(self, profile_id: UUID) -> list[Service]:
        """Весь прайс профиля под блокировкой строк (порядок, лимит) — по позиции."""
        self._uow.require_active()
        stmt = (
            select(ServiceRow)
            .where(ServiceRow.profile_id == profile_id, ServiceRow.deleted_at.is_(None))
            .order_by(ServiceRow.position, ServiceRow.created_at)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        services = [_to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
        for service in services:
            self._uow.track(service)
        return services

    async def get_for_update(self, profile_id: UUID, service_id: ServiceId) -> Service:
        self._uow.require_active()
        stmt = (
            select(ServiceRow)
            .where(
                ServiceRow.id == service_id,
                ServiceRow.profile_id == profile_id,
                ServiceRow.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ServiceNotFoundError(service_id=service_id)
        service = _to_domain(row)
        self._uow.track(service)
        return service

    async def add(self, service: Service) -> None:
        self._uow.require_active()
        row = ServiceRow(id=service.id, created_at=service.created_at)
        _apply(service, row)
        self._session.add(row)
        await self._session.flush()
        self._uow.track(service)

    async def save(self, service: Service) -> None:
        self._uow.require_active()
        row = await self._session.get(ServiceRow, service.id)
        if row is None:
            raise ServiceNotFoundError(service_id=service.id)
        _apply(service, row)
        await self._session.flush()
        self._uow.track(service)

    async def delete(self, service: Service, *, now: datetime) -> None:
        self._uow.require_active()
        row = await self._session.get(ServiceRow, service.id)
        if row is not None:
            row.deleted_at = now
            await self._session.flush()

    async def has_active(self, profile_id: UUID) -> bool:
        stmt = select(func.count()).where(
            ServiceRow.profile_id == profile_id,
            ServiceRow.deleted_at.is_(None),
            ServiceRow.is_active,
        )
        return int((await self._session.execute(stmt)).scalar_one()) > 0

    async def summary(self, profile_id: UUID) -> PriceSummary:
        undescribed = func.coalesce(func.btrim(ServiceRow.description), "") == ""
        stmt = select(func.count(), func.count().filter(undescribed)).where(
            ServiceRow.profile_id == profile_id,
            ServiceRow.deleted_at.is_(None),
            ServiceRow.is_active,
        )
        items, without_description = (await self._session.execute(stmt)).one()
        return PriceSummary(items=int(items), without_description=int(without_description))


def _to_domain(row: ServiceRow) -> Service:
    return Service(
        id=ServiceId(row.id),
        profile_id=row.profile_id,
        title=row.title,
        price_type=row.price_type,
        created_at=row.created_at,
        description=row.description,
        category_id=CategoryId(row.category_id) if row.category_id is not None else None,
        price_min=row.price_min,
        price_max=row.price_max,
        unit=row.unit,
        duration_min=row.duration_min,
        position=row.position,
        is_active=row.is_active,
    )


def _apply(service: Service, row: ServiceRow) -> None:
    row.profile_id = service.profile_id
    row.category_id = service.category_id
    row.title = service.title
    row.description = service.description
    row.price_type = service.price_type
    row.price_min = service.price_min
    row.price_max = service.price_max
    row.unit = service.unit
    row.duration_min = service.duration_min
    row.position = service.position
    row.is_active = service.is_active
