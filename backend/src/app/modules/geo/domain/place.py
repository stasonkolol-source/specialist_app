"""Город и район (ARCHITECTURE §7.6): перечисления справочника."""

from enum import StrEnum


class DistrictKind(StrEnum):
    MUNICIPALITY = "municipality"
    NEIGHBORHOOD = "neighborhood"


class CityStatus(StrEnum):
    ACTIVE = "active"
    SOON = "soon"
    """Город виден в списке с пометкой «скоро» (пробел §8.5), выбрать его ещё нельзя."""
