"""Типы колонок для доменных value objects (ARCHITECTURE §7.1, docs/spikes/0.6)."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, override

from geoalchemy2 import Geography
from geoalchemy2.shape import to_shape
from sqlalchemy import BigInteger, CheckConstraint, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Currency

MoneyAmount = BigInteger
"""Сумма в минимальных единицах валюты. Пара колонок: `<name>_amount` + `<name>_currency`."""


def str_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """StrEnum в колонке text + CHECK (дешевле менять, чем PostgreSQL ENUM)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(m.value) for m in enum_cls) + 8,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def rsd_only(currency_column: str) -> CheckConstraint:
    """Цены, бюджеты и отклики — только RSD (ст. 34 Zakon o deviznom poslovanju)."""
    return CheckConstraint(
        f"{currency_column} = '{Currency.RSD.value}'", name=f"{currency_column}_rsd"
    )


class LocalizedTextType(TypeDecorator[LocalizedText]):
    """LocalizedText ↔ JSONB {"ru": …, "sr-Latn": …}. CHECK — localized_text_check()."""

    impl = JSONB
    cache_ok = True

    @override
    def process_bind_param(
        self, value: LocalizedText | Mapping[str, str] | None, dialect: Dialect
    ) -> Any:
        if value is None:
            return None
        return value.to_mapping() if isinstance(value, LocalizedText) else dict(value)

    @override
    def process_result_value(self, value: Any, dialect: Dialect) -> LocalizedText | None:
        return None if value is None else LocalizedText.from_mapping(value)


def localized_text_check(column: str) -> CheckConstraint:
    """Объект, непустой, ключи — только известные локали."""
    locales = ", ".join(f"'{loc.value}'" for loc in Locale)
    return CheckConstraint(
        f"jsonb_typeof({column}) = 'object' AND {column} <> '{{}}'::jsonb "
        f"AND ({column} - ARRAY[{locales}]::text[]) = '{{}}'::jsonb",
        name=f"{column}_locales",
    )


class GeoPointType(TypeDecorator[GeoPoint]):
    """GeoPoint ↔ geography(POINT, 4326). Запись — EWKT через ST_GeogFromText (GeoAlchemy2),
    чтение — WKB → shapely. Индекс — явный GiST (spatial_index=False, спайк 0.6)."""

    impl = Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    cache_ok = True

    @override
    def process_bind_param(self, value: GeoPoint | None, dialect: Dialect) -> str | None:
        return None if value is None else value.to_ewkt()

    @override
    def process_result_value(self, value: Any, dialect: Dialect) -> GeoPoint | None:
        if value is None:
            return None
        point = to_shape(value)
        return GeoPoint(lat=float(point.y), lon=float(point.x))
