"""Импорт города и районов из сидов (DEVELOPMENT_PLAN 1.3a, `cli seed`)."""

from dataclasses import dataclass

from app.modules.geo.application.dto import CitySeed, ImportResult
from app.modules.geo.application.ports import GeoWriter
from app.platform.db.port import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportCityCommand:
    seed: CitySeed


class ImportCity:
    def __init__(self, uow: UnitOfWork, writer: GeoWriter) -> None:
        self._uow, self._writer = uow, writer

    async def __call__(self, cmd: ImportCityCommand) -> ImportResult:
        async with self._uow:
            return await self._writer.upsert_city(cmd.seed)
