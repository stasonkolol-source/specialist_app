"""Мои отклики (GET /me/responses, S17; DEVELOPMENT_PLAN 5.4): отклики исполнителя страницами,
новые первыми, с заявкой; числа на чипах групп и «сегодня откликов: 3 из 50»."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, ResponseQuota
from app.modules.jobs.application.responses import MyResponse, ResponseGroup, TodayQuota
from app.modules.jobs.application.use_cases.respond import TRUSTED_LEVEL
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMyResponsesCommand:
    actor_id: UserId
    trust_level: int
    group: ResponseGroup | None
    page: PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class MyResponses:
    page: Page[MyResponse]
    counts: dict[ResponseGroup, int]
    today: TodayQuota


class ListMyResponses:
    def __init__(self, queries: JobQueries, quota: ResponseQuota) -> None:
        self._queries, self._quota = queries, quota

    async def __call__(self, cmd: ListMyResponsesCommand) -> MyResponses:
        page = await self._queries.my_responses(cmd.actor_id, cmd.group, page=cmd.page)
        counts = await self._queries.my_response_counts(cmd.actor_id)
        today = await self._quota.today(cmd.actor_id, trusted=cmd.trust_level >= TRUSTED_LEVEL)
        return MyResponses(page=page, counts=counts, today=today)
