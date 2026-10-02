"""Строки read-model для тестов выдачи (4.2): как их написал бы проектор 4.1."""

from datetime import UTC, datetime
from typing import Any

from app.modules.search.domain.index import IndexEntry, SearchDocument, serbian
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
CITY = CityId(910_001)
REPAIR, ELECTRIC, PLUMBING = CategoryId(9_001), CategoryId(9_002), CategoryId(9_003)
CENTER = GeoPoint(lat=45.2551, lon=19.8452)
FIVE_KM_NORTH = GeoPoint(lat=45.2551 + 0.045, lon=19.8452)
ELECTRICIAN = SearchDocument(
    names_ru="Электрик", names_sr=serbian("Električar ; Електричар"), names_en="Electrician"
)
PLUMBER = SearchDocument(
    names_ru="Сантехник", names_sr="Vodoinstalater ; Водоинсталатер", names_en="Plumber"
)


def entry(name: str, **fields: Any) -> IndexEntry:
    values: dict[str, Any] = {
        "profile_id": new_id(),
        "user_id": UserId(new_id()),
        "kind": "pro",
        "is_listed": True,
        "city_id": CITY,
        "district_id": None,
        "district_ids": (),
        "base_point": CENTER,
        "base_point_public": CENTER,
        "travel_radius_m": None,
        "category_ids": (REPAIR, ELECTRIC),
        "languages": ("ru",),
        "work_modes": ("at_client",),
        "price_from": None,
        "category_prices": {},
        "available_until": None,
        "activity_score": 0.5,
        "score": 0.05,
        "name": name,
        "document": ELECTRICIAN,
        "card": {"display_name": name, "kind": fields.get("kind", "pro")},
        "source_updated_at": NOW,
    }
    return IndexEntry(**(values | fields))
