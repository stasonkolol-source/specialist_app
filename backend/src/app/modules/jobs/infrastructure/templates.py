"""Шаблоны откликов в PostgreSQL (S57, DEVELOPMENT_PLAN 5.5). Создание и порядок шаблонов
исполнителя сериализует advisory lock транзакции по пользователю: два параллельных «Новый
шаблон» не дадут третьего."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.response import Offer
from app.modules.jobs.domain.template import ResponseTemplate, TemplateId
from app.modules.jobs.infrastructure.models import ResponseTemplateRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

_T = ResponseTemplateRow.__table__.c


class SqlResponseTemplates:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def lock(self, user_id: UserId) -> None:
        self._uow.require_active()
        key = func.hashtextextended(f"jobs.templates:{user_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def of_user(self, user_id: UserId) -> list[ResponseTemplate]:
        rows = (
            await self._session.execute(
                select(ResponseTemplateRow)
                .where(_T.user_id == user_id, _T.deleted_at.is_(None))
                .order_by(_T.position, _T.created_at)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [_template(row) for row in rows]

    async def add(self, template: ResponseTemplate) -> None:
        self._uow.require_active()
        row = ResponseTemplateRow(
            id=template.id, user_id=template.user_id, created_at=template.created_at
        )
        _apply(template, row)
        self._session.add(row)
        await self._session.flush()

    async def save(self, template: ResponseTemplate) -> None:
        self._uow.require_active()
        row = await self._session.get(ResponseTemplateRow, template.id)
        if row is not None:
            _apply(template, row)
            await self._session.flush()

    async def delete(self, template_id: TemplateId, *, now: datetime) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(ResponseTemplateRow)
            .where(_T.id == template_id)
            .values(deleted_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(ResponseTemplateRow)
            .where(_T.user_id == user_id)
            .values(
                deleted_at=func.coalesce(_T.deleted_at, func.now()),
                message="—",
                title="—",
                availability_note=None,
            )
            .execution_options(synchronize_session=False)
        )


def _template(row: ResponseTemplateRow) -> ResponseTemplate:
    return ResponseTemplate(
        id=TemplateId(row.id),
        user_id=UserId(row.user_id),
        title=row.title,
        offer=Offer(
            message=row.message,
            price_type=row.price_type,
            price_amount=row.price_amount,
            availability_note=row.availability_note,
        ),
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply(template: ResponseTemplate, row: ResponseTemplateRow) -> None:
    offer = template.offer
    row.title = template.title
    row.message = offer.message
    row.price_type = offer.price_type
    row.price_amount = offer.price_amount
    row.availability_note = offer.availability_note
    row.position = template.position
    row.updated_at = template.updated_at
