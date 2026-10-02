"""Этапы разбора запроса выдачи (ARCHITECTURE §9.2; DEVELOPMENT_PLAN 4.2): общие для выдачи
и для подсчёта «Показать N» — иначе число в шторке разошлось бы со страницей.

Словарь категорий (целиком или по началу) → FTS: все слова → по началу слов → любое слово →
ближайшее слово словаря. Узнанная категория не даёт подсказки: она уже ответ.
"""

from collections.abc import AsyncIterator

from app.modules.catalog.api import CatalogApi
from app.modules.search.application.dto import TextMatch
from app.modules.search.domain.query import FTS_STAGES, QueryText, Stage


class QueryStages:
    def __init__(self, catalog: CatalogApi) -> None:
        self._catalog = catalog

    async def __call__(
        self, text: QueryText | None, only: Stage | None = None
    ) -> AsyncIterator[tuple[TextMatch | None, str | None]]:
        """Этапы по порядку: чем сузить выдачу и что подсказать. С курсором — только его
        этап: словарь и подсказка находятся заново, они детерминированы."""
        if text is None:
            yield None, None
            return
        taxonomy = None
        if only in {None, Stage.TAXONOMY}:
            taxonomy = await self._catalog.match_query(text.raw)
            if taxonomy is not None:
                yield TextMatch(stage=Stage.TAXONOMY, category_ids=taxonomy.category_ids), None
        for stage in FTS_STAGES:
            if only in {None, stage}:
                yield TextMatch(stage=stage, fts=text.fts(stage), name=text.raw), None
        if only in {None, Stage.SIMILAR} and taxonomy is None:
            similar = await self._catalog.similar_term(text.raw)
            if similar is not None:
                match = TextMatch(stage=Stage.SIMILAR, category_ids=similar.category_ids)
                yield match, similar.term
