"""Выгрузка данных search (DEVELOPMENT_PLAN 2.12b): избранное пользователя.

Read-model выдачи — копия профиля из specialists, журнал запросов — без пользователя: в
выгрузку не идут.
"""

from app.modules.search.infrastructure.models import FavoriteRow
from app.platform.privacy.registry import ExportTable, export_section

export_section("search", ExportTable(FavoriteRow, lambda user: FavoriteRow.user_id == user))
