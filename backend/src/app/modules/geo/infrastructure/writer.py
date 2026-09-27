"""Импорт сидов geo: upsert по slug, неизменённые записи не трогаются (seed_hash)."""

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.application.dto import CitySeed, DistrictSeed, ImportResult
from app.modules.geo.domain.place import DistrictKind
from app.modules.geo.infrastructure.models import CityRow, DistrictRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.translit import sr_cyrl_to_latn


def with_latin(name: LocalizedText) -> LocalizedText:
    """sr-Latn генерируется из sr-Cyrl, если не задан явно (ARCHITECTURE §7.4)."""
    values = dict(name.values)
    if Locale.SR_LATN not in values and Locale.SR_CYRL in values:
        values[Locale.SR_LATN] = sr_cyrl_to_latn(values[Locale.SR_CYRL])
    return LocalizedText(values)


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _geometry(wkt: str | None) -> object:
    return func.ST_GeomFromText(wkt, 4326) if wkt is not None else None


class SqlGeoWriter:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def upsert_city(self, seed: CitySeed) -> ImportResult:
        self._uow.require_active()
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        name = with_latin(seed.name)
        city_hash = _hash(
            [
                seed.slug,
                name.to_mapping(),
                seed.center,
                seed.active,
                seed.sort_order,
                seed.boundary_wkt,
            ]
        )
        city_id = await self._upsert(
            CityRow,
            {"slug": seed.slug},
            {
                "name": name,
                "center": seed.center,
                "boundary": _geometry(seed.boundary_wkt),
                "is_active": seed.active,
                "sort_order": seed.sort_order,
                "seed_hash": city_hash,
            },
            counts,
        )
        ids: dict[str, int] = {}
        ordered = sorted(seed.districts, key=lambda d: d.kind is not DistrictKind.MUNICIPALITY)
        for district in ordered:
            parent_id = ids[district.parent] if district.parent else None
            ids[district.slug] = await self._upsert(
                DistrictRow,
                {"city_id": city_id, "slug": district.slug},
                self._district_values(district, parent_id),
                counts,
            )
        return ImportResult(**counts)

    def _district_values(self, district: DistrictSeed, parent_id: int | None) -> dict[str, object]:
        name = with_latin(district.name)
        payload = [
            district.kind.value,
            parent_id,
            name.to_mapping(),
            list(district.aliases),
            district.center,
            district.boundary_wkt,
            district.source,
        ]
        return {
            "parent_id": parent_id,
            "kind": district.kind,
            "name": name,
            "aliases": list(district.aliases),
            "center": district.center,
            "boundary": _geometry(district.boundary_wkt),
            "source": district.source,
            "seed_hash": _hash(payload),
        }

    async def _upsert(
        self,
        row: type[CityRow] | type[DistrictRow],
        keys: dict[str, object],
        values: dict[str, object],
        counts: dict[str, int],
    ) -> int:
        table = row.__table__
        existing = (
            await self._session.execute(
                select(table.c.id, table.c.seed_hash).where(
                    *(table.c[column] == value for column, value in keys.items())
                )
            )
        ).one_or_none()
        if existing is not None and existing.seed_hash == values["seed_hash"]:
            counts["unchanged"] += 1
            return int(existing.id)
        statement = (
            insert(row)
            .values(**keys, **values)
            .on_conflict_do_update(index_elements=list(keys), set_=values)
            .returning(row.id)
        )
        new_id = (await self._session.execute(statement)).scalar_one()
        counts["updated" if existing is not None else "created"] += 1
        return int(new_id)
