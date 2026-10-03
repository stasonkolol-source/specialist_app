"""Фасад search (ADR-0020 §6): карточка специалиста (BFF S08) читает из read-model то, что
считает поиск, — время ответа (6.3b)."""

from uuid import UUID

from app.modules.search.application.ports import SpecialistIndex


class SearchFacade:
    def __init__(self, index: SpecialistIndex) -> None:
        self._index = index

    async def response_time(self, profile_id: UUID) -> int | None:
        return await self._index.response_time(profile_id)
