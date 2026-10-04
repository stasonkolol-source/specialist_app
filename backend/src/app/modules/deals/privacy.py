"""Выгрузка данных deals (DEVELOPMENT_PLAN 2.12b): сделки, где пользователь — сторона, их
история и споры.

Правила хранения нет: завершённые сделки хранятся обезличенными для статистики (§7.10), а
идущий спор — legal hold для переписки и файлов (фасад deals: `disputed_deals`).
"""

from uuid import UUID

from sqlalchemy import ColumnElement, Select, or_, select

from app.modules.deals.infrastructure.models import DealRow, DisputeRow, StatusHistoryRow
from app.platform.privacy.registry import ExportTable, export_section


def _party(user_id: UUID) -> ColumnElement[bool]:
    return or_(DealRow.client_id == user_id, DealRow.performer_id == user_id)


def _deals(user_id: UUID) -> Select[UUID]:
    return select(DealRow.id).where(_party(user_id))


export_section(
    "deals",
    ExportTable(DealRow, _party),
    ExportTable(StatusHistoryRow, lambda user: StatusHistoryRow.deal_id.in_(_deals(user))),
    ExportTable(DisputeRow, lambda user: DisputeRow.deal_id.in_(_deals(user))),
)
