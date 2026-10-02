"""`cli reindex --all` (DEVELOPMENT_PLAN 4.1): пересобрать read-model поиска в процессе CLI.

Сверка отмечает все опубликованные профили и все строки индекса, пачки пересобираются здесь
же — воркер не нужен, итог виден сразу. Нужна после смены формулы балла или состава строки,
после восстановления базы и для проверки стенда.
"""

from dataclasses import dataclass

from dishka import AsyncContainer

from app.modules.search.application.use_cases.flush_index import FlushIndex, FlushIndexCommand
from app.modules.search.application.use_cases.reconcile_index import (
    ReconcileIndex,
    ReconcileIndexCommand,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReindexReport:
    published: int
    indexed_before: int
    rebuilt: int
    removed: int


async def reindex_all(container: AsyncContainer) -> ReindexReport:
    async with container() as request:
        marked = await (await request.get(ReconcileIndex))(ReconcileIndexCommand())
    rebuilt = removed = 0
    more = True
    while more:
        async with container() as request:
            report = await (await request.get(FlushIndex))(FlushIndexCommand())
        rebuilt, removed, more = rebuilt + report.indexed, removed + report.removed, report.more
    return ReindexReport(
        published=marked.published,
        indexed_before=marked.indexed,
        rebuilt=rebuilt,
        removed=removed,
    )
