"""Отчёт по запросам без результатов (DEVELOPMENT_PLAN 4.3b; ARCHITECTURE §9.2): еженедельный
разбор — что люди ищут и не находят. Запрос без фильтров с пустой выдачей — пробел в словаре
категорий или нехватка специалистов; с фильтрами — чаще фильтры слишком узкие.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.search.application.dto import ZeroResultStat
from app.modules.search.application.ports import QueryLog
from app.platform.kernel.clock import Clock

DEFAULT_DAYS: Final = 7
DEFAULT_LIMIT: Final = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportZeroResultsCommand:
    days: int = DEFAULT_DAYS
    limit: int = DEFAULT_LIMIT


class ReportZeroResults:
    def __init__(self, log: QueryLog, clock: Clock) -> None:
        self._log, self._clock = log, clock

    async def __call__(self, cmd: ReportZeroResultsCommand) -> list[ZeroResultStat]:
        since = self._clock.now() - timedelta(days=cmd.days)
        return await self._log.zero_results(since, limit=cmd.limit)
