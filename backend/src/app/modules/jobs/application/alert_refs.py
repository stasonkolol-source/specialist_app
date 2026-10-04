"""Подписка ссылается на справочники (S19, DEVELOPMENT_PLAN 5.7): категории есть и открыты (стоп-
категорию и выключенную не выбрать), город открыт, районы — этого города. Проверка — чтение,
до транзакции, как у содержимого заявки (content.py)."""

from app.modules.catalog.api import CatalogApi, RiskLevel
from app.modules.geo.api import GeoApi
from app.modules.jobs.domain.alert import AlertCriteria
from app.modules.jobs.errors import InvalidAlertError


async def check_refs(catalog: CatalogApi, geo: GeoApi, criteria: AlertCriteria) -> None:
    found = {
        category.id
        for category in await catalog.categories(criteria.category_ids)
        if category.is_active and category.risk_level < RiskLevel.FORBIDDEN
    }
    if any(category_id not in found for category_id in criteria.category_ids):
        raise InvalidAlertError(field="category_ids", reason="unavailable")
    city = await geo.city(criteria.city_id)
    if city is None or not city.is_active:
        raise InvalidAlertError(field="city_id", reason="unavailable")
    if criteria.district_ids:
        districts = await geo.districts(criteria.district_ids)
        if any(
            district_id not in districts or districts[district_id].city_id != city.id
            for district_id in criteria.district_ids
        ):
            raise InvalidAlertError(field="district_ids", reason="not_in_city")
