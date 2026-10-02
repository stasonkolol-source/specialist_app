"""Подсказки при вводе (DEVELOPMENT_PLAN 4.3a; ARCHITECTURE §9.7).

Категории словаря по началу слова и по похожести — через фасад catalog. Ответ одинаков для
всех, а набор текста — запрос на каждую букву, словарь же меняется редко: ответ живёт
5 минут в кэше. Ключ — ввод без регистра и лишних пробелов, но в своём алфавите: от алфавита
зависит, каким словом показать категорию («елек» → «Електричар», «elek» → «Električar»).
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from app.modules.catalog.api import CatalogApi, CategorySuggestion
from app.modules.search.domain.query import readable
from app.platform.cache.port import JsonCache
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import LocalizedText

SUGGESTIONS: Final = 8
CACHE_TTL: Final = timedelta(minutes=5)
CACHE_KEY: Final = "search.suggest:v1:"
MIN_INPUT: Final = 2
MAX_INPUT: Final = 64


@dataclass(frozen=True, slots=True, kw_only=True)
class SuggestCategoriesCommand:
    q: str


class SuggestCategories:
    def __init__(self, catalog: CatalogApi, cache: JsonCache) -> None:
        self._catalog, self._cache = catalog, cache

    async def __call__(self, cmd: SuggestCategoriesCommand) -> list[CategorySuggestion]:
        typed = " ".join(readable(cmd.q).split())[:MAX_INPUT]
        if len(typed) < MIN_INPUT:
            return []
        key = CACHE_KEY + typed.casefold()
        cached = _restore(await self._cache.get(key))
        if cached is not None:
            return cached
        found = await self._catalog.suggest(typed, limit=SUGGESTIONS)
        await self._cache.set(key, [_dump(item) for item in found], ttl=CACHE_TTL)
        return found


def _dump(item: CategorySuggestion) -> dict[str, Any]:
    return {
        "category_id": item.category_id,
        "name": item.name.to_mapping(),
        "icon": item.icon,
        "term": item.term,
        "fuzzy": item.fuzzy,
    }


def _restore(value: object) -> list[CategorySuggestion] | None:
    """Значение из кэша или None: нет его или формат не тот — спросим словарь заново."""
    if not isinstance(value, list):
        return None
    try:
        return [
            CategorySuggestion(
                category_id=CategoryId(int(item["category_id"])),
                name=LocalizedText.from_mapping(item["name"]),
                icon=item["icon"],
                term=str(item["term"]),
                fuzzy=bool(item["fuzzy"]),
            )
            for item in value
        ]
    except KeyError, TypeError, ValueError, AttributeError:
        return None
