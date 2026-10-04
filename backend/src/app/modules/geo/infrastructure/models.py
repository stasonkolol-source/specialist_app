"""ORM-модели geo (ARCHITECTURE §7.3, §7.6, миграция geo_0001).

Точки — geography(Point, 4326): расстояния в метрах. Границы — geometry(MultiPolygon, 4326)
под GiST: `ST_Covers` по индексу (ADR-0005). GiST объявлены явно (spatial_index=False,
спайк 0.6). `seed_hash` — хэш исходных данных сида: повторный `cli seed` ничего не меняет.
`name_origin = admin` — название поправили в админке (2.7b, geo_0002): импорт его не переписывает.
"""

from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.geo.domain.place import DistrictKind
from app.platform.db.base import ModelBase, module_metadata
from app.platform.db.types import (
    GeoPointType,
    LocalizedTextType,
    NameOrigin,
    localized_text_check,
    str_enum,
)
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.localized import LocalizedText

SCHEMA = "geo"
metadata = module_metadata(SCHEMA)

IMPORT_LOCK = 0x67656F5F63697479
"""pg_advisory_xact_lock справочника городов и районов: «geo_city» в hex. Берут импорт `cli seed`
(writer.py) и правка в админке (admin/views.py, 2.7b)."""

BOUNDARY = Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


def _required_locales(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ?& ARRAY['ru', 'sr-Cyrl']", name=f"{column}_required_locales")


class CityRow(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[LocalizedText] = mapped_column(LocalizedTextType)
    center: Mapped[GeoPoint] = mapped_column(GeoPointType)
    boundary: Mapped[Any | None] = mapped_column(BOUNDARY)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    seed_hash: Mapped[str | None] = mapped_column(String(64))
    name_origin: Mapped[NameOrigin] = mapped_column(
        str_enum(NameOrigin, "name_origin"), server_default=NameOrigin.SEED.value
    )

    __table_args__ = (
        localized_text_check("name"),
        _required_locales("name"),
        Index("ix_cities_boundary", "boundary", postgresql_using="gist"),
    )


class DistrictRow(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    kind: Mapped[DistrictKind] = mapped_column(str_enum(DistrictKind, "kind"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[LocalizedText] = mapped_column(LocalizedTextType)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(64)), server_default=text("'{}'"))
    center: Mapped[GeoPoint] = mapped_column(GeoPointType)
    boundary: Mapped[Any | None] = mapped_column(BOUNDARY)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    source: Mapped[str] = mapped_column(String(64))
    seed_hash: Mapped[str | None] = mapped_column(String(64))
    name_origin: Mapped[NameOrigin] = mapped_column(
        str_enum(NameOrigin, "name_origin"), server_default=NameOrigin.SEED.value
    )

    __table_args__ = (
        Index("uq_districts_city_id_slug", "city_id", "slug", unique=True),
        localized_text_check("name"),
        _required_locales("name"),
        Index("ix_districts_boundary", "boundary", postgresql_using="gist"),
        Index("ix_districts_center", "center", postgresql_using="gist"),
    )
