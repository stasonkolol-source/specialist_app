"""Метрики ликвидности и алерт (DEVELOPMENT_PLAN 6.6): известный ответ на своих данных.

Данные — строками в транзакции теста и в 2020 году: данные других тестов (они пишут «сейчас»)
в окно отчёта не попадают, и ответ точный. Неделя 1 беты — со 2 марта 2020 (Белград, UTC+1).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.analytics.alerts import check_response_rate, send_alert
from app.platform.analytics.beta_report import render, render_weeks
from app.platform.analytics.liquidity import (
    Ratio,
    beta_weeks,
    liquidity_report,
    reporting_connection,
    week_window,
)
from app.platform.kernel.ids import new_id
from app.platform.settings import DbSettings
from app.platform.testing.telegram import RecordingTelegramSender
from tests.plugins.containers import PostgresInfo

pytestmark = pytest.mark.integration

BETA_START = date(2020, 3, 2)
AS_OF = datetime(2020, 5, 15, 12, tzinfo=UTC)
REGISTERED = datetime(2020, 2, 1, 9, tzinfo=UTC)


def at(day: int, hour: int, minute: int = 0, *, month: int = 3) -> datetime:
    return datetime(2020, month, day, hour, minute, tzinfo=UTC)


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


def hours(n: int) -> timedelta:
    return timedelta(hours=n)


class Data:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def run(self, sql: str, **params: Any) -> Any:
        return await self.conn.execute(text(sql), params)

    async def setup(self) -> None:
        self.city = (await self.run("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")).scalar()
        rows = (
            await self.run(
                "SELECT DISTINCT ON (path[1]) id, path FROM catalog.categories"
                " WHERE parent_id IS NOT NULL AND is_active ORDER BY path[1], id"
            )
        ).all()
        (self.cat_a, self.path_a), (self.cat_b, self.path_b) = rows[0], rows[1]

    async def user(self, created: datetime = REGISTERED) -> UUID:
        user_id = new_id()
        await self.run(
            "INSERT INTO identity.users (id, display_name, version, created_at)"
            " VALUES (:id, 'Ana', 1, :created)",
            id=user_id,
            created=created,
        )
        return user_id

    async def job(
        self,
        client: UUID,
        published: datetime,
        *,
        pair: str = "a",
        status: str = "published",
    ) -> tuple[UUID, datetime]:
        job_id = new_id()
        category, path = (self.cat_a, self.path_a) if pair == "a" else (self.cat_b, self.path_b)
        await self.run(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, budget_min, city_id,"
            " published_at, expires_at, created_at, version) VALUES (:id, :client, :status,"
            " 'Повесить люстру', 'Люстра', 'ru', :category, :path, 'this_week', 'fixed', 500000,"
            " :city, :published, :expires, :published, 1)",
            id=job_id,
            client=client,
            status=status,
            category=category,
            path=list(path),
            city=self.city,
            published=published,
            expires=published + timedelta(days=7),
        )
        return job_id, published

    async def response(
        self, job: tuple[UUID, datetime], performer: UUID, after: timedelta, review: str = "clear"
    ) -> UUID:
        response_id = new_id()
        await self.run(
            "INSERT INTO jobs.responses (id, job_id, performer_id, status, message, price_type,"
            " review, created_at) VALUES (:id, :job, :performer, 'submitted', 'Сделаю',"
            " 'negotiable', :review, :created)",
            id=response_id,
            job=job[0],
            performer=performer,
            review=review,
            created=job[1] + after,
        )
        return response_id

    async def deal(
        self,
        client: UUID,
        performer: UUID,
        *,
        agreed: datetime | None,
        status: str,
        job: tuple[UUID, datetime] | None = None,
        response: UUID | None = None,
        completed: datetime | None = None,
        created: datetime | None = None,
    ) -> UUID:
        deal_id = new_id()
        await self.run(
            "INSERT INTO deals.deals (id, client_id, performer_id, origin, job_id, response_id,"
            " title_snapshot, category_id, status, agreed_at, completed_at, created_at, version)"
            " VALUES (:id, :client, :performer, :origin, :job, :response, 'Люстра', :category,"
            " :status, :agreed, :completed, :created, 1)",
            id=deal_id,
            client=client,
            performer=performer,
            origin="job_response" if job else "direct",
            job=job[0] if job else None,
            response=response,
            category=self.cat_a,
            status=status,
            agreed=agreed,
            completed=completed,
            created=created or agreed,
        )
        return deal_id


@pytest.fixture
async def data(db_connection: AsyncConnection, geo_seeded: None, catalog_seeded: None) -> Data:
    created = Data(db_connection)
    await created.setup()
    return created


async def test_week_report_has_known_answer(data: Data) -> None:
    c1, c2, c3, c4, c5 = [await data.user() for _ in range(5)]
    p1, p2, p3, p4, p5 = [await data.user() for _ in range(5)]

    # пара A: четыре заявки, J3 — ночная (23:30 по Белграду) и без откликов
    j1 = await data.job(c1, at(3, 9))  # 10:00 по Белграду
    r1 = await data.response(j1, p1, minutes(20))
    await data.response(j1, p2, minutes(50))
    await data.response(j1, p3, hours(3))
    j2 = await data.job(c1, at(4, 11))
    await data.response(j2, p2, hours(2))
    await data.response(j2, p4, hours(5))
    await data.job(c2, at(5, 22, 30))
    j4 = await data.job(c3, at(6, 8))
    await data.response(j4, p1, minutes(30))
    r4 = await data.response(j4, p3, hours(5))
    await data.response(j4, p4, minutes(10), review="blocked")  # скрыт модерацией — не считается
    await data.job(c3, at(6, 10), status="removed")  # снята модерацией — не в метриках
    # пара B: одна заявка, три быстрых отклика
    j5 = await data.job(c4, at(7, 14), pair="b")
    await data.response(j5, p1, minutes(10))
    r5 = await data.response(j5, p2, minutes(15))
    await data.response(j5, p3, minutes(30))

    d1 = await data.deal(
        c1, p1, job=j1, response=r1, agreed=at(4, 9), status="completed", completed=at(6, 9)
    )
    # выбор через 8 дней: в fill rate@7d не входит, в win rate — входит
    await data.deal(c3, p3, job=j4, response=r4, agreed=at(14, 8), status="agreed")
    await data.deal(c4, p2, job=j5, response=r5, agreed=at(7, 16), status="cancelled")
    # прямые сделки без заявки — только в итог
    await data.deal(c5, p2, agreed=at(5, 10), status="completed", completed=at(7, 10))
    await data.deal(c4, p1, agreed=None, status="proposed", created=at(1, 10, month=4))

    for performer in (p1, p2, p3, p5):
        await data.run(
            "INSERT INTO specialists.profiles (id, user_id, kind, status, display_name, city_id,"
            " created_at, published_at, version) VALUES (:id, :user, 'pro', 'published', 'Ivan',"
            " :city, :at, :at, 1)",
            id=new_id(),
            user=performer,
            city=data.city,
            at=REGISTERED,
        )
    v1, v2, v3 = [await data.user(at(5, 12)) for _ in range(3)]
    for user, source, code in ((v1, "job", None), (v2, "organic", "r1"), (v3, "organic", None)):
        await data.run(
            "INSERT INTO growth.attributions (user_id, source, referral_code, first_seen_at)"
            " VALUES (:user, :source, :code, :at)",
            user=user,
            source=source,
            code=code,
            at=at(5, 12),
        )
    channels: list[tuple[UUID, datetime, datetime | None]]
    channels = [(u, at(2, 9), None) for u in (c1, c2, p1, p2, p3, v1)]
    channels += [(c3, at(2, 9), at(5, 9)), (c4, at(10, 9), None)]
    for user, granted, disabled in channels:
        await data.run(
            "INSERT INTO notifications.channels (id, user_id, kind, address, granted_via,"
            " granted_at, disabled_at) VALUES (:id, :user, 'telegram', :address, 'bot_start',"
            " :granted, :disabled)",
            id=new_id(),
            user=user,
            address=str(700_000_000 + new_id().int % 100_000_000),
            granted=granted,
            disabled=disabled,
        )
    await data.run(
        "INSERT INTO reviews.reviews (id, kind, deal_id, author_id, subject_user_id, direction,"
        " rating, status, published_at, version) VALUES (:id, 'deal', :deal, :author, :subject,"
        " 'client_to_performer', 5, 'published', :at, 1)",
        id=new_id(),
        deal=d1,
        author=c1,
        subject=p1,
        at=at(7, 9),
    )
    # одна открытая жалоба на пару «кто — на кого» (uq_reports_open): вторая — на другого
    for reason, target in (("fraud", p4), ("spam", p3)):
        await data.run(
            "INSERT INTO moderation.reports (id, reporter_id, target_type, target_id, reason,"
            " created_at) VALUES (:id, :reporter, 'user', :target, :reason, :at)",
            id=new_id(),
            reporter=c1,
            target=target,
            reason=reason,
            at=at(5, 9),
        )
    cases = [  # очередь, срок, решён через (None — открыт)
        ("premod", minutes(30), minutes(20)),
        ("premod", minutes(30), minutes(45)),
        ("safety", hours(1), None),
        ("fraud", hours(2), hours(1)),
    ]
    for queue, due, decided in cases:
        await data.run(
            "INSERT INTO moderation.cases (id, queue, entity_type, entity_id, subject_id,"
            " trigger, status, due_at, decided_at, created_at) VALUES (:id, :queue, 'job',"
            " :entity, :subject, 'report', :status, :due, :decided, :created)",
            id=new_id(),
            queue=queue,
            entity=new_id(),
            subject=c2,
            status="pending" if decided is None else "approved",
            due=at(5, 9) + due,
            decided=None if decided is None else at(5, 9) + decided,
            created=at(5, 9),
        )

    report = await liquidity_report(data.conn, week_window(BETA_START, 1), as_of=AS_OF)

    o = report.overall
    assert o.jobs == 5
    assert (o.rr_1h, o.rr_4h, o.rr_24h) == (Ratio(3, 4), Ratio(4, 5), Ratio(4, 5))
    assert o.first_hour_three_a_day == Ratio(2, 4)
    assert o.ttfr_minutes == pytest.approx(25.0)
    assert o.depth == pytest.approx(2.0)
    assert o.fill_7d == Ratio(2, 5)
    assert o.completion == Ratio(2, 3)
    assert o.win_rate == pytest.approx(1 / 3)
    assert o.active_specialists == 4
    assert o.supply_demand == pytest.approx(0.8)
    assert o.deals_completed == 2

    assert [(p.category_id, p.metrics.jobs) for p in report.pairs] == [
        (data.path_a[0], 4),
        (data.path_b[0], 1),
    ]
    a, b = report.pairs[0].metrics, report.pairs[1].metrics
    assert report.pairs[0].city == "Нови-Сад"
    assert (a.rr_1h, a.rr_4h, a.first_hour_three_a_day) == (Ratio(2, 3), Ratio(3, 4), Ratio(1, 3))
    assert a.ttfr_minutes == pytest.approx(30.0)
    assert (a.depth, a.fill_7d) == (2.0, Ratio(1, 4))
    assert a.win_rate == pytest.approx(0.25)
    assert a.active_specialists == 4
    assert (a.completion, a.deals_completed) == (Ratio(1, 1), 1)
    assert (b.rr_1h, b.first_hour_three_a_day, b.fill_7d) == (Ratio(1, 1), Ratio(1, 1), Ratio(1, 1))
    assert b.ttfr_minutes == pytest.approx(10.0)
    assert (b.depth, b.win_rate) == (3.0, 0.0)
    assert (b.completion, b.supply_demand) == (Ratio(0, 1), 3.0)

    assert report.active_profiles == Ratio(3, 4)
    assert report.opt_in == Ratio(6, 13)
    assert report.repeat_60d == Ratio(2, 4)
    assert report.k_factor == Ratio(2, 8)
    assert report.review_rate == Ratio(1, 2)
    assert report.fraud_reports == Ratio(1, 3)
    assert dict(report.moderation_sla) == {
        "fraud": Ratio(1, 1),
        "premod": Ratio(1, 2),
        "safety": Ratio(0, 1),
    }
    assert report.concentration == pytest.approx(2 / 3)

    text_report = render(report, week=1)
    assert "неделя 1: 02.03.2020 – 08.03.2020" in text_report
    assert "Response rate@4h: 80% (4/5)" in text_report
    assert "Нови-Сад × " in text_report
    assert "Доля KYC: v1" in text_report


async def test_all_weeks_from_first_to_current(data: Data) -> None:
    """`cli beta-report --week all` (7.7): недели 1…текущая, у каждой — свои заявки и отклики."""
    client, performer = await data.user(), await data.user()
    first = await data.job(client, at(3, 9))  # неделя 1: отклик через 20 минут
    await data.response(first, performer, minutes(20))
    await data.job(client, at(10, 9))  # неделя 2: без откликов

    reports = await beta_weeks(data.conn, BETA_START, as_of=at(18, 12))  # среда недели 3

    assert [week for week, _ in reports] == [1, 2, 3]
    assert [r.overall.rr_1h for _, r in reports] == [Ratio(1, 1), Ratio(0, 1), Ratio(0, 0)]
    assert reports[0][1].overall.ttfr_minutes == pytest.approx(20.0)
    table = render_weeks(reports, beta_start=BETA_START).splitlines()
    assert any(line.startswith("| 1: 02.03–08.03 | 1 | 100% (1/1) |") for line in table)
    assert any(line.startswith("| 2: 09.03–15.03 | 1 | 0% (0/1) |") for line in table)
    assert any(line.startswith("| 3: 16.03–22.03 | 0 | — (0/0) |") for line in table)


async def test_response_rate_alert_fires_on_drop(data: Data) -> None:
    client, performer = await data.user(), await data.user()
    as_of = at(15, 7, 5, month=6)
    for n in range(10):
        job = await data.job(client, as_of - timedelta(days=6, hours=n))
        if n < 3:
            await data.response(job, performer, timedelta(hours=1))
        elif n < 5:  # отклик позже 4 ч — не спасает
            await data.response(job, performer, timedelta(hours=6))

    alert = await check_response_rate(data.conn, as_of=as_of, threshold=0.7, min_jobs=10)

    assert alert is not None
    assert alert.overall == Ratio(3, 10)
    assert [name.startswith("Нови-Сад × ") for name, _ in alert.pairs] == [True]
    sender = RecordingTelegramSender()
    await send_alert(alert, sender=sender, chat_id=-100500)
    [message] = sender.sent
    assert message.chat_id == -100500
    assert "Response rate@4h за 7 дней — 30% (3/10), порог 70%." in message.text
    # без чата модераторов — лог и Sentry, отправки нет
    await send_alert(alert, sender=None, chat_id=None)
    assert len(sender.sent) == 1

    # выше порога или мало заявок — тишина
    assert await check_response_rate(data.conn, as_of=as_of, threshold=0.3, min_jobs=10) is None
    assert await check_response_rate(data.conn, as_of=as_of, threshold=0.7, min_jobs=11) is None


@pytest.mark.parametrize("role", ["readonly", "app"])
async def test_report_reads_and_cannot_write(postgres: PostgresInfo, role: str) -> None:
    """Под ролью readonly (её права на схемы модулей) и под app без DSN readonly — только чтение."""
    readonly = SecretStr(postgres.dsn("readonly")) if role == "readonly" else None
    db = DbSettings(dsn=SecretStr(postgres.dsn("app")), readonly_dsn=readonly)
    async with reporting_connection(db) as conn:
        report = await liquidity_report(conn, week_window(BETA_START, 1), as_of=AS_OF)
        assert report.overall.jobs == 0
        with pytest.raises(DBAPIError, match="read-only"):
            await conn.execute(text("DELETE FROM jobs.jobs"))
