"""Импорт города и районов из сидов (DEVELOPMENT_PLAN 1.3a, `cli seed`)."""

from dataclasses import dataclass

from app.modules.geo.application.dto import CitySeed, ImportResult
from app.modules.geo.application.ports import DirectoryCache, GeoWriter
from app.platform.db.port import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportCityCommand:
    seed: CitySeed


class ImportCity:
    def __init__(self, uow: UnitOfWork, writer: GeoWriter, cache: DirectoryCache) -> None:
        self._uow, self._writer, self._cache = uow, writer, cache

    async def __call__(self, cmd: ImportCityCommand) -> ImportResult:
        async with self._uow:
            result = await self._writer.upsert_city(cmd.seed)
        self._cache.invalidate()
        return result
