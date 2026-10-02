"""Отчёт по запросам без результатов (DEVELOPMENT_PLAN 4.3b): один запрос в разных написаниях —
одна строка с самым частым написанием, языками и подсказкой; самые частые — первыми; старше
окна — не в отчёте."""

from datetime import UTC, datetime, timedelta

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.search.application.dto import ZeroResult
from app.modules.search.application.use_cases.report_zero_results import (
    ReportZeroResults,
    ReportZeroResultsCommand,
)
from app.modules.search.infrastructure.query_log import SqlQueryLog
from app.platform.kernel.ids import CityId
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
CITY = CityId(990_003)


def zero(
    q: str, locale: str = "ru", *, filters: tuple[str, ...] = (), hint: str | None = None
) -> ZeroResult:
    return ZeroResult(
        q=q,
        locale=locale,
        city_id=CITY,
        category_id=None,
        filters=filters,
        did_you_mean=hint,
    )


async def test_report_groups_spellings_and_puts_the_most_frequent_first(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    uow = make_uow(db_session, procrastinate_app)
    log = SqlQueryLog(db_session, uow)
    entries = [
        zero("ремонт кондиционера"),
        zero("ремонт кондиционера"),
        zero("Ремонт кондиционера"),
        zero("ремонт  кондиционера", filters=("district_ids",)),
        zero("servis klime", "sr-Latn", hint="Električar"),
        zero("servis klime", "sr-Latn"),
        zero("старое"),
    ]
    async with uow:
        for entry in entries:
            await log.record(entry)
    await db_session.execute(
        text("UPDATE search.query_log SET created_at = :at WHERE city_id = :c AND q = 'старое'"),
        {"at": NOW - timedelta(days=30), "c": CITY},
    )
    await db_session.execute(
        text("UPDATE search.query_log SET created_at = :at WHERE city_id = :c AND q <> 'старое'"),
        {"at": NOW - timedelta(hours=1), "c": CITY},
    )
    # чтение отчёта откатывает транзакцию без UoW: фиксируем savepoint теста
    await db_session.commit()

    report = ReportZeroResults(log, FakeClock(NOW))
    stats = [s for s in await report(ReportZeroResultsCommand(days=7)) if s.q != "старое"]

    ours = [s for s in stats if s.q in {"ремонт кондиционера", "servis klime"}]
    assert [(s.q, s.count, s.narrowed) for s in ours] == [
        ("ремонт кондиционера", 4, 1),
        ("servis klime", 2, 0),
    ]
    assert ours[1].locales == ("sr-Latn",)
    assert ours[1].did_you_mean == "Električar"
    assert all(s.q != "старое" for s in await report(ReportZeroResultsCommand(days=7)))
