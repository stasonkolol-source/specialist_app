"""Фасад search (ADR-0020 §6): карточка специалиста (BFF S08) читает из read-model то, что
считает поиск, — время ответа (6.3b)."""

from collections.abc import Collection
from uuid import UUID

from app.modules.search.application.ports import SpecialistIndex


class SearchFacade:
    def __init__(self, index: SpecialistIndex) -> None:
        self._index = index

    async def response_time(self, profile_id: UUID) -> int | None:
        return await self._index.response_time(profile_id)

    async def response_times(self, profile_ids: Collection[UUID]) -> dict[UUID, int]:
        return await self._index.response_times(profile_ids) if profile_ids else {}
