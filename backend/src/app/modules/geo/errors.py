"""Ошибки модуля geo со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import NotFoundError


class CityNotFoundError(NotFoundError):
    code = "city_not_found"


class OutsideServiceAreaError(NotFoundError):
    """Точка дальше MAX_NEAREST_KM от любого района активного города."""

    code = "outside_service_area"


class OutsideCityError(NotFoundError):
    """Район по точке (S20b, карта): точка не в районе города и дальше NEAR_CITY_KM от него."""

    code = "outside_city"
