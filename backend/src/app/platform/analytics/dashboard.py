"""Дашборд ликвидности PostHog как код (DEVELOPMENT_PLAN 6.6, K32).

Плитка — метрика PRODUCT, которую можно посчитать по событиям таксономии (events.py): тренды
по неделям, доли формулой и воронки. Ворота беты решает `cli beta-report` — SQL «на момент» с
окном по каждой заявке; здесь — динамика и разрез. Доли по формуле считаются по неделе события:
отклик в понедельник на заявку из воскресенья попадёт в другую неделю, чем заявка.

Разрез — только где его несут свойства событий: у `job_published` есть город и категория, у
сделок — только категория, у отклика — ни того, ни другого (`is_first`,
`minutes_since_published`), поэтому метрики откликов — без разреза. Город и категория — id
справочников `geo.cities` и `catalog.categories`; названия — в `cli beta-report`.

Метрики, которых по событиям не посчитать, перечислены в текстовой плитке. Каждый запрос
фильтрует свойство `environment`: stage и prod могут жить в одном проекте PostHog.

Применяет `cli posthog-dashboard --apply` (posthog_dashboard.py).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.platform.analytics.beta_report import PENDING
from app.platform.analytics.events import EventName
from app.platform.analytics.liquidity import DAY_END, DAY_START
from app.platform.kernel.clock import BUSINESS_TZ

TAG_PREFIX: Final = "sosed-liquidity"
DATE_FROM: Final = "-8w"
"""Шесть недель беты и неделя до старта; диапазон меняют фильтром дашборда."""
TEXT_MARKER: Final = "## Метрики вне дашборда"
"""Заголовок текстовой плитки — по нему её находит повторный `--apply` (у текста нет тегов)."""

SQL_ONLY: Final[Mapping[str, str]] = {
    "Глубина": "медиана откликов на заявку за 24 ч; цель 3–5",
    "Доля активных среди профилей": "откликались за неделю; цель ≥ 30%",
    "Repeat rate клиентов": "вторая заявка или прямой заказ за 60 дней; цель ≥ 25%",
    "K-фактор шаринга": "новые по ссылкам и рефералам на активного; трекать",
    "SLA модерации": "решено в срок по очередям; цель ≥ 95%",
    "Концентрация": "доля выборов у топ-10% специалистов; цель ≤ 50%",
}
"""Метрики PRODUCT, которые считает только SQL отчёта: нужны состояние базы или счёт по
каждой заявке и исполнителю, а события несут только факт."""

type Query = dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class InsightSpec:
    key: str
    """Стабильный ключ — тег `<тег дашборда>:<key>`: переименование плитки не плодит копию."""
    metric: str | None
    """Метрика PRODUCT (как в METRICS); None — контекстная плитка."""
    name: str
    description: str
    query: Query


@dataclass(frozen=True, slots=True, kw_only=True)
class DashboardSpec:
    environment: str
    name: str
    description: str
    tag: str
    insights: tuple[InsightSpec, ...]
    text: str

    def insight_tag(self, insight: InsightSpec) -> str:
        return f"{self.tag}:{insight.key}"


def _event(
    name: EventName,
    *filters: dict[str, Any],
    math: str | None = None,
    math_property: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"kind": "EventsNode", "event": name.value, "name": name.value}
    if math:
        node["math"] = math
    if math_property:
        node["math_property"] = math_property
    if filters:
        node["properties"] = list(filters)
    return node


def _is(key: str, value: str) -> dict[str, Any]:
    # булевы свойства PostHog сравнивает строкой — так фильтр сохраняет и интерфейс
    return {"type": "event", "key": key, "operator": "exact", "value": [value]}


def _at_most(key: str, value: int) -> dict[str, Any]:
    return {"type": "event", "key": key, "operator": "lte", "value": value}


def _hogql(expression: str) -> dict[str, Any]:
    return {"type": "hogql", "key": expression}


def _daytime(moment: str) -> dict[str, Any]:
    """Опубликовано с 08:00 до 22:00 по Белграду — как DAY_START/DAY_END отчёта."""
    hour = f"toHour(toTimeZone({moment}, '{BUSINESS_TZ.key}'))"
    return _hogql(f"{hour} >= {DAY_START} and {hour} < {DAY_END}")


_PUBLISHED_AT: Final = "timestamp - toIntervalMinute(toInt(properties.minutes_since_published))"
"""Время публикации заявки по событию отклика."""
_PAIR: Final = {
    "breakdown_type": "hogql",
    "breakdown": "concat(toString(properties.city), ' × ', toString(properties.category))",
}
_CATEGORY: Final = {"breakdown_type": "event", "breakdown": "category"}


def _first_response_within(minutes: int, *extra: dict[str, Any]) -> dict[str, Any]:
    return _event(
        EventName.RESPONSE_SUBMITTED,
        _is("is_first", "true"),
        _at_most("minutes_since_published", minutes),
        *extra,
    )


def _goals(*goals: tuple[str, float]) -> list[dict[str, Any]]:
    return [{"label": label, "value": value} for label, value in goals]


def _trends(
    environment: str,
    series: Sequence[dict[str, Any]],
    *,
    formula: str | None = None,
    breakdown: Mapping[str, str] | None = None,
    display: str = "ActionsLineGraph",
    axis: str = "numeric",
    goals: Sequence[tuple[str, float]] = (),
) -> Query:
    trends_filter: dict[str, Any] = {"display": display, "aggregationAxisFormat": axis}
    if formula:
        trends_filter["formula"] = formula
    if goals:
        trends_filter["goalLines"] = _goals(*goals)
    source: dict[str, Any] = {
        "kind": "TrendsQuery",
        "series": list(series),
        "interval": "week",
        "dateRange": {"date_from": DATE_FROM},
        "properties": [_is("environment", environment)],
        "trendsFilter": trends_filter,
    }
    if breakdown:
        source["breakdownFilter"] = dict(breakdown)
    return {"kind": "InsightVizNode", "source": source}


def _funnel(
    environment: str,
    steps: Sequence[dict[str, Any]],
    *,
    window_days: int,
    breakdown: Mapping[str, str] | None = None,
    ordered: bool = True,
) -> Query:
    source: dict[str, Any] = {
        "kind": "FunnelsQuery",
        "series": list(steps),
        "dateRange": {"date_from": DATE_FROM},
        "properties": [_is("environment", environment)],
        "funnelsFilter": {
            "funnelVizType": "steps",
            "funnelOrderType": "ordered" if ordered else "unordered",
            "funnelWindowInterval": window_days,
            "funnelWindowIntervalUnit": "day",
        },
    }
    if breakdown:
        # разрез — по первому шагу: город и категория заявки (сделки)
        source["breakdownFilter"] = dict(breakdown)
    return {"kind": "InsightVizNode", "source": source}


def _insights(env: str) -> tuple[InsightSpec, ...]:
    e = EventName
    client, performer = _is("role", "client"), _is("role", "performer")
    by_response = _is("origin", "job_response")
    jobs = _event(e.JOB_PUBLISHED)
    rate = "percentage_scaled"
    note = " Точная доля по окну каждой заявки — в cli beta-report."
    return (
        InsightSpec(
            key="north_star",
            metric=None,
            name="North Star: завершённые сделки",
            description="Сделки, завершённые за неделю (копия события клиента — одна на "
            "сделку), по категориям. North Star PRODUCT: порога нет, смотрим рост неделя к "
            "неделе.",
            query=_trends(
                env,
                [_event(e.DEAL_COMPLETED, client)],
                breakdown=_CATEGORY,
                display="ActionsBar",
            ),
        ),
        InsightSpec(
            key="jobs",
            metric=None,
            name="Заявки: город × категория",
            description="Опубликованные за неделю заявки (с продлёнными) по паре «город × "
            "категория» (id справочников) — спрос и знаменатель долей ниже. Порога нет.",
            query=_trends(env, [jobs], breakdown=_PAIR, display="ActionsBar"),
        ),
        InsightSpec(
            key="response_rate_1h",
            metric="Response rate@1h",
            name="Response rate@1h (заявки 08:00–22:00)",
            description="Первые отклики за ≤ 60 мин / заявки недели — только опубликованные с "
            "08:00 до 22:00 по Белграду. Цель MVP ≥ 80% (v1 ≥ 85%); нижний порог пересмотра — "
            "60%." + note,
            query=_trends(
                env,
                [
                    _first_response_within(60, _daytime(_PUBLISHED_AT)),
                    _event(e.JOB_PUBLISHED, _daytime("timestamp")),
                ],
                formula="A / B",
                axis=rate,
                goals=(("Цель MVP 80%", 0.8), ("Порог пересмотра 60%", 0.6)),
            ),
        ),
        InsightSpec(
            key="response_rate_4h",
            metric="Response rate@4h",
            name="Response rate@4h",
            description="Первые отклики за ≤ 4 ч / заявки недели. Цель MVP ≥ 70% (v1 ≥ 85%); "
            "ворота монетизации — 4 недели подряд ≥ 70%; ниже порога — алерт в чат "
            "модераторов." + note,
            query=_trends(
                env,
                [_first_response_within(240), jobs],
                formula="A / B",
                axis=rate,
                goals=(("Цель MVP 70%", 0.7),),
            ),
        ),
        InsightSpec(
            key="response_rate_24h",
            metric="Response rate@24h",
            name="Response rate@24h",
            description="Первые отклики за ≤ 24 ч / заявки недели. Цель MVP ≥ 85% (v1 ≥ 95%)."
            + note,
            query=_trends(
                env,
                [_first_response_within(24 * 60), jobs],
                formula="A / B",
                axis=rate,
                goals=(("Цель MVP 85%", 0.85),),
            ),
        ),
        InsightSpec(
            key="ttfr",
            metric="TTFR",
            name="TTFR — медиана минут до первого отклика",
            description="Медиана minutes_since_published у первых откликов недели. Цель MVP ≤ "
            "60 мин, ворота открытия категории — < 30 мин (v1 ≤ 20 мин).",
            query=_trends(
                env,
                [
                    _event(
                        e.RESPONSE_SUBMITTED,
                        _is("is_first", "true"),
                        math="median",
                        math_property="minutes_since_published",
                    )
                ],
                goals=(("Цель MVP 60 мин", 60), ("Ворота 30 мин", 30)),
            ),
        ),
        InsightSpec(
            key="fill_rate_7d",
            metric="Fill rate@7d",
            name="Fill rate@7d: город × категория",
            description="Воронка клиента: заявка → договорились по отклику за 7 дней; разрез — "
            "город и категория заявки. Цель MVP ≥ 35%, ворота — ≥ 40% (v1 ≥ 50%); нижний порог "
            "пересмотра — 25%. Воронка считает клиентов, а не заявки." + note,
            query=_funnel(
                env,
                [jobs, _event(e.DEAL_AGREED, client, by_response)],
                window_days=7,
                breakdown=_PAIR,
            ),
        ),
        InsightSpec(
            key="completion_rate",
            metric="Completion rate",
            name="Completion rate",
            description="Воронка клиента: договорились → выполнено за 30 дней, по категориям. "
            "Цель MVP ≥ 60% (v1 ≥ 75%).",
            query=_funnel(
                env,
                [_event(e.DEAL_AGREED, client), _event(e.DEAL_COMPLETED, client)],
                window_days=30,
                breakdown=_CATEGORY,
            ),
        ),
        InsightSpec(
            key="win_rate",
            metric="Win rate отклика",
            name="Win rate откликов (общая доля)",
            description="Договорились по отклику (копия исполнителя) / отклики недели. Цель — "
            "медиана по исполнителям ≥ 10% (ворота монетизации ≥ 15%); медиана — в cli "
            "beta-report.",
            query=_trends(
                env,
                [_event(e.DEAL_AGREED, performer, by_response), _event(e.RESPONSE_SUBMITTED)],
                formula="A / B",
                axis=rate,
                goals=(("Цель MVP 10%", 0.10), ("Монетизация 15%", 0.15)),
            ),
        ),
        InsightSpec(
            key="supply_demand",
            metric="Supply/demand",
            name="Supply/demand: откликавшиеся на заявку",
            description="Исполнители с откликом за неделю / заявки недели. Цель 3–10.",
            query=_trends(
                env,
                [_event(e.RESPONSE_SUBMITTED, math="dau"), jobs],
                formula="A / B",
                goals=(("3", 3), ("10", 10)),
            ),
        ),
        InsightSpec(
            key="weekly_active_specialists",
            metric="Weekly active specialists",
            name="Weekly active specialists",
            description="Исполнители с ≥ 1 откликом за неделю. Цель MVP 80–150 на пилотную зону "
            "(v1 ×3).",
            query=_trends(
                env,
                [_event(e.RESPONSE_SUBMITTED, math="dau")],
                goals=(("Цель MVP 80", 80),),
            ),
        ),
        InsightSpec(
            key="opt_in",
            metric="Opt-in уведомлений",
            name="Opt-in уведомлений: новые пользователи",
            description="Воронка: регистрация и разрешение боту писать за 7 дней (в любом "
            "порядке: /start в боте делает и то, и другое). Цель ≥ 70% (v1 ≥ 80%). Доля на "
            "конец недели с учётом заблокировавших бота — в cli beta-report.",
            query=_funnel(
                env,
                [_event(e.USER_REGISTERED), _event(e.WRITE_ACCESS_GRANTED)],
                window_days=7,
                ordered=False,
            ),
        ),
        InsightSpec(
            key="review_rate",
            metric="Review rate",
            name="Review rate",
            description="Воронка клиента: сделка выполнена → отзыв опубликован за 14 дней (окно "
            "отзыва), по категориям. Цель MVP ≥ 40% (v1 ≥ 55%); ворота открытия категории — "
            "≥ 30%.",
            query=_funnel(
                env,
                [_event(e.DEAL_COMPLETED, client), _event(e.REVIEW_PUBLISHED)],
                window_days=14,
                breakdown=_CATEGORY,
            ),
        ),
        InsightSpec(
            key="fraud_reports",
            metric="Жалобы на мошенничество",
            name="Жалобы на мошенничество на 1 000 сделок",
            description="Жалобы с причиной «мошенничество» / договорённые сделки недели × 1000. "
            "Цель MVP < 5 (v1 < 2).",
            query=_trends(
                env,
                [_event(e.REPORT_CREATED, _is("reason", "fraud")), _event(e.DEAL_AGREED, client)],
                formula="A / B * 1000",
                goals=(("Цель MVP 5", 5),),
            ),
        ),
    )


def _text() -> str:
    sql_only = [f"- {name} — {what}" for name, what in SQL_ONLY.items()]
    later = [f"- {name}: {step}" for name, step in PENDING.items()]
    return "\n".join(
        [
            TEXT_MARKER,
            "Ворота беты и go/no-go решает `make cli ARGS='beta-report --week N'` (`--week all` "
            "— все недели): SQL по базе на момент отчёта, окно по каждой заявке, пары «город × "
            "категория» с названиями. Плитки здесь — динамика по событиям: доли по неделе "
            "события, город и категория — id справочников.",
            "",
            "**Только в `cli beta-report`:**",
            *sql_only,
            "",
            "**Позже (шаг):**",
            *later,
            "",
            "Дашборд — код: `backend/src/app/platform/analytics/dashboard.py`. Ручные правки "
            "плиток перезапишет `cli posthog-dashboard --apply`.",
        ]
    )


def liquidity_dashboard(environment: str) -> DashboardSpec:
    """Дашборд для событий одного окружения (свойство `environment`: stage, production)."""
    return DashboardSpec(
        environment=environment,
        name=f"Ликвидность «Соседи» — {environment}",
        description="Метрики ликвидности и ворот беты по событиям (DEVELOPMENT_PLAN 6.6). Цели "
        "— из PRODUCT, в описании каждой плитки; точные доли — в cli beta-report.",
        tag=f"{TAG_PREFIX}-{environment}",
        insights=_insights(environment),
        text=_text(),
    )
