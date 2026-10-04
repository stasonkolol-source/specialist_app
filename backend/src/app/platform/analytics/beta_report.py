"""Еженедельный отчёт беты `cli beta-report --week <N>` (DEVELOPMENT_PLAN 6.6, 7.1, 7.7).

Текст для людей: русские подписи, доля — с числителем и знаменателем, цель MVP из PRODUCT
рядом. Каждая метрика таблицы PRODUCT либо в отчёте (`REPORTED`), либо в `PENDING` с шагом,
который её подключит; тест сверяет оба списка с METRICS.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final

from app.platform.analytics.liquidity import Liquidity, LiquidityReport, Ratio
from app.platform.kernel.clock import BUSINESS_TZ

REPORTED: Final = frozenset(
    {
        "Response rate@1h",
        "Response rate@4h",
        "Response rate@24h",
        "Глубина",
        "TTFR",
        "Fill rate@7d",
        "Completion rate",
        "Win rate отклика",
        "Supply/demand",
        "Weekly active specialists",
        "Доля активных среди профилей",
        "Opt-in уведомлений",
        "Repeat rate клиентов",
        "K-фактор шаринга",
        "Review rate",
        "Жалобы на мошенничество",
        "SLA модерации",
        "Концентрация",
    }
)
"""Метрики PRODUCT, которые считает отчёт 6.6 (SQL под ролью readonly)."""

PENDING: Final[Mapping[str, str]] = {
    "6-месячное удержание": "7.7 — нужны полгода данных; цель MVP — «трекать»",
    "Точность автомодерации": "7.1 — выборочный аудит решений в админке (2.7b)",
    "Доля KYC": "v1 — KYC появляется в v1",
    "GMV proxy": "v1 — бизнес-метрики с v1",
    "Конверсия в Pro": "v1 — billing",
    "ARPPU, LTV:CAC": "v1 — billing",
}
"""Метрики PRODUCT, которых в отчёте нет, — и шаг, который их подключит."""

_QUEUES: Final = {
    "safety": "P0 Safety (≤ 1 ч)",
    "fraud": "P1 Fraud (≤ 2 ч)",
    "premod": "P2 Premod (≤ 30 мин)",
    "appeals": "Appeals (≤ 72 ч)",
}


def render(report: LiquidityReport, *, week: int) -> str:
    start = report.window.start.astimezone(BUSINESS_TZ)
    # конец окна — полночь следующего понедельника: в заголовке — последний день недели
    end = (report.window.end - timedelta(days=1)).astimezone(BUSINESS_TZ)
    as_of = report.as_of.astimezone(BUSINESS_TZ)
    o = report.overall
    lines = [
        f"Отчёт беты «Соседи» — неделя {week}: "
        f"{start:%d.%m.%Y} – {end:%d.%m.%Y} (Белград), данные на {as_of:%d.%m.%Y %H:%M}",
        "Доли — по заявкам, у которых окно уже закрылось; в скобках — сколько из скольких.",
        "",
        "Итог",
        f"  Сделок завершено (North Star): {o.deals_completed}",
        *_liquidity_lines(o),
        "",
        "Стороны и удержание",
        f"  Weekly active specialists (≥ 1 отклик): {o.active_specialists}  [цель 80–150 на зону]",
        _line("Доля активных среди профилей", report.active_profiles, "≥ 30%"),
        _line("Opt-in уведомлений (бот может писать)", report.opt_in, "≥ 70%"),
        _line("Repeat rate клиентов за 60 дней", report.repeat_60d, "≥ 25%"),
        f"  K-фактор шаринга: {_number(report.k_factor.value, 2)} "
        f"({report.k_factor.hits} новых по ссылкам / {report.k_factor.total} активных)"
        "  [трекать; до 7.4 — по атрибуции ссылок]",
        "",
        "Доверие и качество",
        _line("Review rate (сделки с отзывом)", report.review_rate, "≥ 40%"),
        f"  Жалобы на мошенничество на 1 000 сделок: {_per_mille(report.fraud_reports)} "
        f"({report.fraud_reports.hits} жалоб / {report.fraud_reports.total} сделок)  [< 5]",
        "  SLA модерации (решено в срок)  [≥ 95%]:",
        *(
            _line(f"  {_QUEUES.get(queue, queue)}", ratio, None)
            for queue, ratio in report.moderation_sla.items()
        ),
        *(["    кейсов с известным исходом нет"] if not report.moderation_sla else []),
        f"  Концентрация (доля выборов у топ-10%): {_percent(report.concentration)}  [≤ 50%]",
        "",
        "По парам «город × категория»",
    ]
    if not report.pairs:
        lines.append("  заявок за неделю нет")
    for pair in report.pairs:
        lines += ["", f"  {pair.city} × {pair.category}"]
        lines += [f"  {line}" for line in _liquidity_lines(pair.metrics)]
    lines += ["", "Не в отчёте (шаг, который подключит)"]
    lines += [f"  {name}: {step}" for name, step in PENDING.items()]
    lines.append("  Динамика по событиям — дашборд PostHog (`cli posthog-dashboard`, K32).")
    return "\n".join(lines)


WEEK_COLUMNS: Final = (
    "Неделя",
    "Заявки",
    "RR@1h ≥ 80%",
    "≥ 1 за 1 ч и ≥ 3 за 24 ч ≥ 80%",
    "Fill rate@7d ≥ 40%",
    "TTFR < 30 мин",
    "Откликались из профилей ≥ 30%",
    "Repeat 60 дней ≥ 25%",
    "Review rate ≥ 30%",
    "RR@4h ≥ 70%",
    "Win rate ≥ 15%",
    "Сделок завершено",
)
"""Колонки сводки 7.7: ворота открытия категории и монетизации (PRODUCT «Ворота и go / no-go»)
— порог в заголовке колонки."""


def render_weeks(reports: Sequence[tuple[int, LiquidityReport]], *, beta_start: date) -> str:
    """Сводка беты для итогов 7.7: строка — неделя, колонки — метрики ворот с порогами.
    Markdown-таблица — вставляется в docs/checklists/beta-results.md как есть."""
    if not reports:
        return f"Бета ещё не началась: неделя 1 — с {beta_start:%d.%m.%Y}, недель для сводки нет."
    as_of = reports[-1][1].as_of.astimezone(BUSINESS_TZ)
    rows = [WEEK_COLUMNS, tuple("---" for _ in WEEK_COLUMNS)]
    for week, report in reports:
        o = report.overall
        start = report.window.start.astimezone(BUSINESS_TZ)
        end = (report.window.end - timedelta(days=1)).astimezone(BUSINESS_TZ)
        rows.append(
            (
                f"{week}: {start:%d.%m}–{end:%d.%m}",
                str(o.jobs),
                _cell(o.rr_1h),
                _cell(o.first_hour_three_a_day),
                _cell(o.fill_7d),
                _minutes(o.ttfr_minutes),
                _cell(report.active_profiles),
                _cell(report.repeat_60d),
                _cell(report.review_rate),
                _cell(o.rr_4h),
                _percent(o.win_rate),
                str(o.deals_completed),
            )
        )
    return "\n".join(
        [
            f"Итоги беты «Соседи»: недели 1–{reports[-1][0]}, данные на {as_of:%d.%m.%Y %H:%M} "
            "(Белград)",
            "Доли — по заявкам, у которых окно уже закрылось (сколько из скольких); repeat rate "
            "недели появляется через 60 дней, доли текущей недели неполные.",
            "",
            *("| " + " | ".join(row) + " |" for row in rows),
            "",
            "Ворота открытия категории (PRODUCT, п. 1) — все условия: ≥ 1 отклик за 1 ч и ≥ 3 за "
            "24 ч, fill rate, TTFR, доля откликавшихся, repeat rate и review rate. Монетизация "
            "(п. 2) — 4 недели подряд RR@4h ≥ 70%, fill rate ≥ 35% и win rate ≥ 15%. Нижний "
            "порог пересмотра (п. 3): RR@1h < 60%, fill rate < 25% или repeat rate < 10%.",
        ]
    )


def _cell(ratio: Ratio) -> str:
    return f"{_percent(ratio.value)} ({ratio.hits}/{ratio.total})"


def _liquidity_lines(m: Liquidity) -> list[str]:
    return [
        f"  Заявок опубликовано: {m.jobs}",
        _line("Response rate@1h (08:00–22:00)", m.rr_1h, "≥ 80%"),
        _line("Response rate@4h", m.rr_4h, "≥ 70%"),
        _line("Response rate@24h", m.rr_24h, "≥ 85%"),
        _line("≥ 1 отклик за 1 ч и ≥ 3 за 24 ч", m.first_hour_three_a_day, "≥ 80%"),
        f"  Медиана TTFR: {_minutes(m.ttfr_minutes)}  [≤ 60 мин; ворота < 30 мин]",
        f"  Глубина (медиана откликов за 24 ч): {_number(m.depth, 1)}  [3–5]",
        _line("Fill rate@7d", m.fill_7d, "≥ 35%; ворота ≥ 40%"),
        _line("Completion rate", m.completion, "≥ 60%"),
        f"  Медианный win rate: {_percent(m.win_rate)}  [≥ 10%; монетизация ≥ 15%]",
        f"  Supply/demand (активных на заявку): {_number(m.supply_demand, 1)}  [3–10]",
    ]


def _line(label: str, ratio: Ratio, target: str | None) -> str:
    suffix = f"  [{target}]" if target else ""
    return f"  {label}: {_percent(ratio.value)} ({ratio.hits}/{ratio.total}){suffix}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _number(value: float | None, digits: int) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def _minutes(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} мин"


def _per_mille(ratio: Ratio) -> str:
    value = ratio.value
    return "—" if value is None else _number(value * 1000, 1)
