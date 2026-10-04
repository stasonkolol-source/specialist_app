"""Метрики ликвидности и ворот беты (DEVELOPMENT_PLAN 6.6, PRODUCT «Метрики успеха»).

Отчётный слой, а не модуль: только чтение, SQL по схемам модулей, как у BI над базой. Пишет
данные по-прежнему только модуль-владелец (ARCHITECTURE §5.2 п. 6), а здесь нет ни записи, ни
импортов модулей — только их таблицы как опубликованный язык отчётов. Соединение открывает
`reporting_connection`: роль `readonly` (ADR-0005), если задан `DB_READONLY_DSN`, иначе роль
app в транзакции READ ONLY. Снимок один на весь отчёт (REPEATABLE READ): доли не «плывут»
между запросами.

Всё считается «на момент» `as_of`: отклики, сделки и решения позже него не видны, а доля по
окну (1 ч, 4 ч, 24 ч, 7 дней, 60 дней) берёт только заявки, у которых окно уже закрылось. Так
отчёт за прошлую неделю воспроизводим, а неделя, которая ещё идёт, не занижает доли.

Пара «город × категория» — город заявки и корневая категория её пути (`category_path[1]`).
Сделки без заявки (из каталога и чата) пары не имеют и входят только в итог.
"""

import math
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.settings import DbSettings

DAY_START, DAY_END = 8, 22
"""Response rate@1h — по заявкам, опубликованным с 08:00 до 22:00 по Белграду (PRODUCT):
ночью за час не отвечают, и ночные заявки не должны ронять дневную метрику."""
VIRAL_SOURCES: Final = ("job", "specialist", "new_job", "home")
"""Ссылки, которые пересылают люди (карточки заявки и специалиста, «Разместить заявку»,
главная): новый пользователь по ним — приведённый шарингом. Реферал — по `referral_code`."""
TOP_SHARE: Final = 0.10
"""Концентрация: доля выборов у топ-10% специалистов (PRODUCT, R06)."""


@dataclass(frozen=True, slots=True)
class Window:
    """Полуинтервал [start, end) — неделя отчёта."""

    start: datetime
    end: datetime


def week_window(beta_start: date, week: int) -> Window:
    """Неделя N беты: с понедельника `beta_start + 7·(N−1)` 00:00 по Белграду. Неделя 0 — до
    старта (обкатка на своих), неделя 1 — первая неделя беты."""
    if week < 0:
        raise ValueError("week must be >= 0")
    first = beta_start + timedelta(days=7 * (week - 1))
    start = datetime.combine(first, time(), tzinfo=BUSINESS_TZ)
    return Window(start, datetime.combine(first + timedelta(days=7), time(), tzinfo=BUSINESS_TZ))


@dataclass(frozen=True, slots=True)
class Ratio:
    """Доля с числителем и знаменателем: в отчёте видно, на скольких заявках она посчитана."""

    hits: int
    total: int

    @property
    def value(self) -> float | None:
        return self.hits / self.total if self.total else None


@dataclass(frozen=True, slots=True, kw_only=True)
class Liquidity:
    """Ликвидность пары «город × категория» или итога за окно."""

    jobs: int = 0
    rr_1h: Ratio = Ratio(0, 0)
    rr_4h: Ratio = Ratio(0, 0)
    rr_24h: Ratio = Ratio(0, 0)
    first_hour_three_a_day: Ratio = Ratio(0, 0)
    """Ворота открытия категории: ≥ 1 отклик за 1 ч и ≥ 3 за 24 ч (дневные заявки)."""
    ttfr_minutes: float | None = None
    depth: float | None = None
    """Медиана откликов на заявку за 24 ч."""
    fill_7d: Ratio = Ratio(0, 0)
    completion: Ratio = Ratio(0, 0)
    """Сделки, договорённые в окне, — сколько из них уже выполнено."""
    win_rate: float | None = None
    """Медиана доли выбранных откликов у исполнителей, откликавшихся в окне."""
    active_specialists: int = 0
    """Исполнители с ≥ 1 откликом в окне (weekly active specialists для недели)."""
    deals_completed: int = 0
    """North Star: сделки, завершённые в окне."""

    @property
    def supply_demand(self) -> float | None:
        """Активных исполнителей на одну заявку окна."""
        return self.active_specialists / self.jobs if self.jobs else None


@dataclass(frozen=True, slots=True, kw_only=True)
class PairLiquidity:
    city_id: int
    category_id: int
    city: str
    category: str
    metrics: Liquidity


@dataclass(frozen=True, slots=True, kw_only=True)
class LiquidityReport:
    window: Window
    as_of: datetime
    overall: Liquidity
    pairs: tuple[PairLiquidity, ...]
    active_profiles: Ratio
    """Опубликованные профили, откликавшиеся в окне (доля активных среди профилей)."""
    opt_in: Ratio
    """Пользователи с живым каналом Telegram на конец окна."""
    repeat_60d: Ratio
    """Клиенты с первой заявкой в окне: вторая заявка или прямой заказ за 60 дней."""
    k_factor: Ratio
    """Новые по ссылкам шаринга и рефералам / активные пользователи окна."""
    review_rate: Ratio
    fraud_reports: Ratio
    """Жалобы «мошенничество» / договорённые сделки окна (× 1000 — на тысячу сделок)."""
    moderation_sla: Mapping[str, Ratio] = field(default_factory=dict)
    concentration: float | None = None


@asynccontextmanager
async def reporting_connection(db: DbSettings) -> AsyncIterator[AsyncConnection]:
    """Соединение отчёта: роль readonly или app в транзакции READ ONLY, один снимок.

    Без пула (NullPool): отчёт — редкая команда и задача раз в сутки, держать соединения
    между ними незачем."""
    dsn = (db.readonly_dsn or db.dsn).get_secret_value()
    engine = create_async_engine(
        dsn, poolclass=NullPool, connect_args={"application_name": "sosed-report"}
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            if db.readonly_dsn is None:
                # у роли app statement_timeout 5 с — отчёт по всей базе в него не уложится
                await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            yield conn
    finally:
        await engine.dispose()


async def liquidity_report(
    conn: AsyncConnection, window: Window, *, as_of: datetime
) -> LiquidityReport:
    """Все метрики отчёта за окно на момент `as_of`. Соединение — `reporting_connection`
    (в тестах — соединение теста)."""
    params = {"start": window.start, "end": window.end, "as_of": as_of}
    by_pair = await pair_liquidity(conn, window, as_of=as_of)
    overall = by_pair.pop(None, Liquidity())
    pairs = {key: metrics for key, metrics in by_pair.items() if key is not None}
    names = await pair_names(conn, pairs.keys())
    side = (
        (await conn.execute(text(_SIDES_SQL), {**params, "viral": list(VIRAL_SOURCES)}))
        .mappings()
        .one()
    )
    sla = {
        row["queue"]: Ratio(row["hits"], row["total"])
        for row in await _rows(conn, _SLA_SQL, params)
    }
    choices = [int(row["choices"]) for row in await _rows(conn, _CHOICES_SQL, params)]
    return LiquidityReport(
        window=window,
        as_of=as_of,
        overall=overall,
        pairs=tuple(
            PairLiquidity(
                city_id=city,
                category_id=category,
                city=names[0].get(city, str(city)),
                category=names[1].get(category, str(category)),
                metrics=metrics,
            )
            for (city, category), metrics in sorted(
                pairs.items(), key=lambda item: (-item[1].jobs, item[0])
            )
        ),
        active_profiles=Ratio(side["active_profiles"], side["profiles"]),
        opt_in=Ratio(side["opted_in"], side["users"]),
        repeat_60d=Ratio(side["repeat_hits"], side["repeat_total"]),
        k_factor=Ratio(side["viral_users"], side["active_users"]),
        review_rate=Ratio(side["reviewed"], side["completed"]),
        fraud_reports=Ratio(side["fraud_reports"], side["deals_agreed"]),
        moderation_sla=sla,
        concentration=concentration(choices, base=int(side["specialists_base"])),
    )


def concentration(choices: Sequence[int], *, base: int) -> float | None:
    """Доля выборов у топ-10% специалистов. База — откликавшиеся или выбранные в окне: топ
    считается от всех, кто боролся за заказы, а не только от тех, кого выбрали."""
    total = sum(choices)
    if not total or not base:
        return None
    top = max(1, math.ceil(base * TOP_SHARE))
    return sum(sorted(choices, reverse=True)[:top]) / total


type PairKey = tuple[int, int] | None


async def pair_liquidity(
    conn: AsyncConnection, window: Window, *, as_of: datetime
) -> dict[PairKey, Liquidity]:
    """Ликвидность по парам и итог (ключ None) — её же читает алерт response rate@4h."""
    params = {
        "start": window.start,
        "end": window.end,
        "as_of": as_of,
        "tz": BUSINESS_TZ.key,
        "day_start": DAY_START,
        "day_end": DAY_END,
    }
    jobs = {_key(row): row for row in await _rows(conn, _JOBS_SQL, params)}
    deals = {_key(row): row for row in await _rows(conn, _DEALS_SQL, params)}
    responders = {_key(row): row for row in await _rows(conn, _RESPONDERS_SQL, params)}
    result: dict[PairKey, Liquidity] = {}
    for key in {*jobs, *deals, *responders}:
        if key is not None and None in key:
            continue  # сделка без заявки: пары нет, она уже в итоге
        result[key] = _liquidity(jobs.get(key), deals.get(key), responders.get(key))
    return result


async def _rows(conn: AsyncConnection, sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in (await conn.execute(text(sql), dict(params))).mappings()]


def _key(row: Mapping[str, Any]) -> PairKey:
    return (row["city_id"], row["category_id"]) if row["is_pair"] else None


def _liquidity(
    jobs: Mapping[str, Any] | None,
    deals: Mapping[str, Any] | None,
    responders: Mapping[str, Any] | None,
) -> Liquidity:
    j: Mapping[str, Any] = jobs or {}
    d: Mapping[str, Any] = deals or {}
    r: Mapping[str, Any] = responders or {}

    def ratio(source: Mapping[str, Any], name: str) -> Ratio:
        return Ratio(int(source.get(f"{name}_hits") or 0), int(source.get(f"{name}_total") or 0))

    return Liquidity(
        jobs=int(j.get("jobs") or 0),
        rr_1h=ratio(j, "rr1h"),
        rr_4h=ratio(j, "rr4h"),
        rr_24h=ratio(j, "rr24h"),
        first_hour_three_a_day=ratio(j, "gate"),
        ttfr_minutes=_float(j.get("ttfr_minutes")),
        depth=_float(j.get("depth")),
        fill_7d=ratio(j, "fill"),
        completion=ratio(d, "completion"),
        win_rate=_float(r.get("win_rate")),
        active_specialists=int(r.get("specialists") or 0),
        deals_completed=int(d.get("completed") or 0),
    )


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


async def pair_names(
    conn: AsyncConnection, keys: Iterable[PairKey]
) -> tuple[dict[int, str], dict[int, str]]:
    """Русские названия городов и категорий пар — для отчёта, не для расчёта."""
    pairs = [key for key in keys if key is not None]
    cities = sorted({city for city, _ in pairs})
    categories = sorted({category for _, category in pairs})
    if not pairs:
        return {}, {}
    city_rows = await conn.execute(
        text("SELECT id, name ->> 'ru' FROM geo.cities WHERE id = ANY(:ids)"), {"ids": cities}
    )
    category_rows = await conn.execute(
        text("SELECT id, name ->> 'ru' FROM catalog.categories WHERE id = ANY(:ids)"),
        {"ids": categories},
    )
    return dict(city_rows.tuples().all()), dict(category_rows.tuples().all())


# Заявки окна: публичные (прямой запрос 5.6 уходит конкретным людям и в ликвидность ленты не
# входит), не снятые модерацией. Отклики — прошедшие или ждущие проверки (скрытые модерацией
# клиенту не видны) и не раньше публикации: продлённая заявка публикуется заново.
_JOBS_SQL = """
WITH job AS (
    SELECT j.id, j.city_id, j.category_path[1] AS category_id, j.published_at,
           extract(hour FROM j.published_at AT TIME ZONE :tz) >= :day_start
           AND extract(hour FROM j.published_at AT TIME ZONE :tz) < :day_end AS daytime
    FROM jobs.jobs j
    WHERE j.published_at >= :start AND j.published_at < :end AND j.published_at < :as_of
      AND j.visibility = 'public' AND j.status <> 'removed'
),
fact AS (
    SELECT job.*, r.first_after,
           coalesce(r.n1h, 0) AS n1h, coalesce(r.n4h, 0) AS n4h, coalesce(r.n24h, 0) AS n24h,
           EXISTS (
               SELECT 1 FROM deals.deals d
               WHERE d.job_id = job.id AND d.agreed_at < :as_of
                 AND d.agreed_at < job.published_at + interval '7 days'
           ) AS filled
    FROM job
    LEFT JOIN LATERAL (
        SELECT min(x.created_at) - job.published_at AS first_after,
               count(*) FILTER (WHERE x.created_at - job.published_at <= interval '1 hour')
                   AS n1h,
               count(*) FILTER (WHERE x.created_at - job.published_at <= interval '4 hours')
                   AS n4h,
               count(*) FILTER (WHERE x.created_at - job.published_at <= interval '24 hours')
                   AS n24h
        FROM jobs.responses x
        WHERE x.job_id = job.id AND x.review <> 'blocked'
          AND x.created_at >= job.published_at AND x.created_at < :as_of
    ) r ON true
)
SELECT GROUPING(city_id, category_id) = 0 AS is_pair, city_id, category_id,
       count(*) AS jobs,
       count(*) FILTER (WHERE daytime AND published_at <= :as_of - interval '1 hour') AS rr1h_total,
       count(*) FILTER (WHERE daytime AND published_at <= :as_of - interval '1 hour'
                        AND n1h > 0) AS rr1h_hits,
       count(*) FILTER (WHERE published_at <= :as_of - interval '4 hours') AS rr4h_total,
       count(*) FILTER (WHERE published_at <= :as_of - interval '4 hours' AND n4h > 0) AS rr4h_hits,
       count(*) FILTER (WHERE published_at <= :as_of - interval '24 hours') AS rr24h_total,
       count(*) FILTER (WHERE published_at <= :as_of - interval '24 hours'
                        AND n24h > 0) AS rr24h_hits,
       count(*) FILTER (WHERE daytime AND published_at <= :as_of - interval '24 hours')
           AS gate_total,
       count(*) FILTER (WHERE daytime AND published_at <= :as_of - interval '24 hours'
                        AND n1h > 0 AND n24h >= 3) AS gate_hits,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM first_after) / 60)
           AS ttfr_minutes,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY n24h)
           FILTER (WHERE published_at <= :as_of - interval '24 hours') AS depth,
       count(*) FILTER (WHERE published_at <= :as_of - interval '7 days') AS fill_total,
       count(*) FILTER (WHERE published_at <= :as_of - interval '7 days' AND filled) AS fill_hits
FROM fact
GROUP BY GROUPING SETS ((city_id, category_id), ())
"""

# Сделки: договорённые в окне (completion) и завершённые в окне (North Star).
_DEALS_SQL = """
WITH deal AS (
    SELECT d.status, d.agreed_at, d.completed_at, j.city_id,
           coalesce(j.category_path[1], c.path[1]) AS category_id
    FROM deals.deals d
    LEFT JOIN jobs.jobs j ON j.id = d.job_id
    LEFT JOIN catalog.categories c ON c.id = d.category_id
    WHERE (d.agreed_at >= :start AND d.agreed_at < :end AND d.agreed_at < :as_of)
       OR (d.completed_at >= :start AND d.completed_at < :end AND d.completed_at < :as_of)
)
SELECT GROUPING(city_id, category_id) = 0 AS is_pair, city_id, category_id,
       count(*) FILTER (WHERE agreed_at >= :start AND agreed_at < :end AND agreed_at < :as_of)
           AS completion_total,
       count(*) FILTER (WHERE agreed_at >= :start AND agreed_at < :end AND agreed_at < :as_of
                        AND status = 'completed' AND completed_at < :as_of) AS completion_hits,
       count(*) FILTER (WHERE status = 'completed' AND completed_at >= :start
                        AND completed_at < :end AND completed_at < :as_of) AS completed
FROM deal
GROUP BY GROUPING SETS ((city_id, category_id), ())
"""

# Исполнители, откликавшиеся в окне: их число (weekly active specialists, supply/demand) и
# медиана доли откликов, по которым договорились (win rate).
_RESPONDERS_SQL = """
WITH r AS (
    SELECT x.performer_id, j.city_id, j.category_path[1] AS category_id,
           EXISTS (
               SELECT 1 FROM deals.deals d
               WHERE d.response_id = x.id AND d.agreed_at < :as_of
           ) AS won
    FROM jobs.responses x
    JOIN jobs.jobs j ON j.id = x.job_id
    WHERE x.created_at >= :start AND x.created_at < :end AND x.created_at < :as_of
      AND x.review <> 'blocked'
),
per AS (
    SELECT GROUPING(city_id, category_id) = 0 AS is_pair, city_id, category_id, performer_id,
           CAST(count(*) FILTER (WHERE won) AS float) / count(*) AS win
    FROM r
    GROUP BY GROUPING SETS ((performer_id, city_id, category_id), (performer_id))
)
SELECT is_pair, city_id, category_id, count(*) AS specialists,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY win) AS win_rate
FROM per
GROUP BY is_pair, city_id, category_id
"""

# Метрики без пары: стороны, удержание, доверие. Состояния (профили, каналы) — на конец окна.
_SIDES_SQL = """
WITH responders AS (
    SELECT DISTINCT performer_id AS user_id FROM jobs.responses
    WHERE created_at >= :start AND created_at < :end AND created_at < :as_of
      AND review <> 'blocked'
),
profile AS (
    SELECT p.user_id FROM specialists.profiles p
    WHERE p.status = 'published' AND p.deleted_at IS NULL AND p.created_at < :end
),
first_job AS (
    SELECT client_id, min(published_at) AS first_at FROM jobs.jobs
    WHERE published_at IS NOT NULL AND status <> 'removed'
    GROUP BY client_id
),
cohort AS (
    SELECT * FROM first_job
    WHERE first_at >= :start AND first_at < :end AND first_at <= :as_of - interval '60 days'
),
active AS (
    SELECT client_id AS user_id FROM jobs.jobs
    WHERE published_at >= :start AND published_at < :end AND published_at < :as_of
    UNION
    SELECT user_id FROM responders
)
SELECT
    (SELECT count(*) FROM profile) AS profiles,
    (SELECT count(*) FROM profile JOIN responders USING (user_id)) AS active_profiles,
    (SELECT count(*) FROM identity.users u
     WHERE u.deleted_at IS NULL AND u.created_at < :end) AS users,
    (SELECT count(*) FROM identity.users u
     WHERE u.deleted_at IS NULL AND u.created_at < :end
       AND EXISTS (
           SELECT 1 FROM notifications.channels ch
           WHERE ch.user_id = u.id AND ch.kind = 'telegram' AND ch.granted_at < :end
             AND (ch.disabled_at IS NULL OR ch.disabled_at >= :end)
       )) AS opted_in,
    (SELECT count(*) FROM cohort) AS repeat_total,
    (SELECT count(*) FROM cohort c
     WHERE EXISTS (
               SELECT 1 FROM jobs.jobs j
               WHERE j.client_id = c.client_id AND j.status <> 'removed'
                 AND j.published_at > c.first_at
                 AND j.published_at <= c.first_at + interval '60 days'
           )
        OR EXISTS (
               SELECT 1 FROM deals.deals d
               WHERE d.client_id = c.client_id AND d.job_id IS NULL
                 AND d.created_at > c.first_at
                 AND d.created_at <= c.first_at + interval '60 days'
           )) AS repeat_hits,
    (SELECT count(*) FROM identity.users u
     JOIN growth.attributions a ON a.user_id = u.id
     WHERE u.created_at >= :start AND u.created_at < :end AND u.created_at < :as_of
       AND (a.referral_code IS NOT NULL
            OR a.source = ANY(:viral))) AS viral_users,
    (SELECT count(*) FROM active) AS active_users,
    (SELECT count(*) FROM deals.deals d
     WHERE d.status = 'completed' AND d.completed_at >= :start AND d.completed_at < :end
       AND d.completed_at < :as_of) AS completed,
    (SELECT count(*) FROM deals.deals d
     WHERE d.status = 'completed' AND d.completed_at >= :start AND d.completed_at < :end
       AND d.completed_at < :as_of
       AND EXISTS (
           SELECT 1 FROM reviews.reviews r
           WHERE r.deal_id = d.id AND r.status = 'published' AND r.published_at < :as_of
       )) AS reviewed,
    (SELECT count(*) FROM moderation.reports
     WHERE reason = 'fraud' AND created_at >= :start AND created_at < :end
       AND created_at < :as_of) AS fraud_reports,
    (SELECT count(*) FROM deals.deals
     WHERE agreed_at >= :start AND agreed_at < :end AND agreed_at < :as_of) AS deals_agreed,
    (SELECT count(*) FROM (
        SELECT user_id FROM responders
        UNION
        SELECT performer_id FROM deals.deals
        WHERE agreed_at >= :start AND agreed_at < :end AND agreed_at < :as_of
    ) s) AS specialists_base
"""

# SLA модерации: кейсы, заведённые в окне, у которых исход уже известен — решены или срок
# прошёл. Решённые в срок / известные. Открытый кейс до срока ещё может уложиться.
_SLA_SQL = """
SELECT queue,
       count(*) FILTER (WHERE decided_at < :as_of AND decided_at <= due_at) AS hits,
       count(*) FILTER (WHERE decided_at < :as_of OR due_at <= :as_of) AS total
FROM moderation.cases
WHERE created_at >= :start AND created_at < :end AND created_at < :as_of
GROUP BY queue
ORDER BY queue
"""

# Выборы окна по исполнителям — для концентрации.
_CHOICES_SQL = """
SELECT count(*) AS choices FROM deals.deals
WHERE agreed_at >= :start AND agreed_at < :end AND agreed_at < :as_of
GROUP BY performer_id
"""
