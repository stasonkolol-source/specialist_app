"""Выгрузка данных growth (DEVELOPMENT_PLAN 2.12b): атрибуция — откуда пришёл пользователь."""

from app.modules.growth.infrastructure.models import AttributionRow
from app.platform.privacy.registry import ExportTable, export_section

export_section("growth", ExportTable(AttributionRow, lambda user: AttributionRow.user_id == user))
