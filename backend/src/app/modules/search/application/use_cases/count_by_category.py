"""Сколько специалистов в каждой категории города (DEVELOPMENT_PLAN 4.4): дерево S04.

Числа меняются с каждой публикацией, а дерево категорий — почти никогда. Поэтому они не в
`GET /categories` (там дерево с ETag), а отдельно: 5 минут в кэше на город.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.search.application.dto import PRO
from app.modules.search.application.ports import SpecialistSearch
from app.platform.cache.port import JsonCache
from app.platform.kernel.ids import CategoryId, CityId

CACHE_TTL: Final = timedelta(minutes=5)
CACHE_KEY: Final = "search.category_counts:v1:"


@dataclass(frozen=True, slots=True, kw_only=True)
class CountByCategoryCommand:
    city_id: CityId
    kind: str = PRO


class CountByCategory:
    def __init__(self, search: SpecialistSearch, cache: JsonCache) -> None:
        self._search, self._cache = search, cache

    async def __call__(self, cmd: CountByCategoryCommand) -> dict[CategoryId, int]:
        key = f"{CACHE_KEY}{cmd.kind}:{cmd.city_id}"
        cached = await self._cache.get(key)
        if isinstance(cached, dict):
            try:
                return {CategoryId(int(k)): int(v) for k, v in cached.items()}
            except TypeError, ValueError:
                pass  # формат не тот — посчитаем заново
        counts = await self._search.count_by_category(cmd.city_id, cmd.kind)
        await self._cache.set(key, {str(k): n for k, n in counts.items()}, ttl=CACHE_TTL)
        return counts
