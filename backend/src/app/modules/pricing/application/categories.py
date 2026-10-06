"""Категория позиции прайса (QA ADV-02): только из каталога и открытая для профилей.

Без проверки несуществующий id доходил до внешнего ключа `services.category_id` — 500 вместо
422. Правило — как у категорий профиля (specialists `allowed_categories`): выключенная и
стоп-категория — тоже нет.
"""

from app.modules.catalog.api import CatalogApi, RiskLevel
from app.modules.pricing.errors import InvalidServiceError
from app.platform.kernel.ids import CategoryId


async def ensure_category(catalog: CatalogApi, category_id: CategoryId | None) -> None:
    if category_id is None:
        return
    summary = await catalog.category(category_id)
    if summary is None or not summary.is_active or summary.risk_level is RiskLevel.FORBIDDEN:
        raise InvalidServiceError(field="category_id")
