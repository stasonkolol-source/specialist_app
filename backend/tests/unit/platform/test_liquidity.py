"""Отчёт ликвидности 6.6 без БД: покрытие таблицы PRODUCT, недели беты, концентрация, текст."""

from datetime import UTC, date, datetime

import pytest

from app.platform.analytics.alerts import ResponseRateAlert
from app.platform.analytics.beta_report import PENDING, REPORTED, WEEK_COLUMNS, render, render_weeks
from app.platform.analytics.events import METRICS
from app.platform.analytics.liquidity import (
    Liquidity,
    LiquidityReport,
    Ratio,
    concentration,
    current_week,
    week_window,
)


def test_every_product_metric_is_reported_or_has_a_step() -> None:
    names = {m.name for m in METRICS}
    assert REPORTED | PENDING.keys() == names
    assert not REPORTED & PENDING.keys()
    assert all(step.split(" ")[0] in {"7.1", "7.7", "v1"} for step in PENDING.values())


def test_week_one_starts_on_beta_monday_in_belgrade() -> None:
    week = week_window(date(2027, 1, 25), 1)
    assert week.start == datetime(2027, 1, 24, 23, tzinfo=UTC)  # 00:00 по Белграду, UTC+1
    assert week.end == datetime(2027, 1, 31, 23, tzinfo=UTC)
    assert week_window(date(2027, 1, 25), 0).end == week.start
    # летнее время: неделя всё равно с полуночи понедельника по Белграду
    assert week_window(date(2027, 1, 25), 9).start == datetime(2027, 3, 21, 23, tzinfo=UTC)
    assert week_window(date(2027, 1, 25), 10).start == datetime(2027, 3, 28, 22, tzinfo=UTC)
    with pytest.raises(ValueError, match="week"):
        week_window(date(2027, 1, 25), -1)


def test_current_week_counts_from_beta_monday_in_belgrade() -> None:
    start = date(2027, 1, 25)
    assert current_week(start, datetime(2027, 1, 24, 22, 59, tzinfo=UTC)) == 0  # 23:59 по Белграду
    assert current_week(start, datetime(2027, 1, 24, 23, tzinfo=UTC)) == 1
    assert current_week(start, datetime(2027, 1, 31, 22, 59, tzinfo=UTC)) == 1
    assert current_week(start, datetime(2027, 1, 31, 23, tzinfo=UTC)) == 2


def test_concentration_is_share_of_top_tenth() -> None:
    # 20 боровшихся за заказы → топ-2; выборы: 5 + 3 из 10
    assert concentration([5, 3, 1, 1], base=20) == pytest.approx(0.8)
    # меньше десяти — топ из одного
    assert concentration([2, 1], base=4) == pytest.approx(2 / 3)
    assert concentration([], base=4) is None


def test_empty_week_renders_dashes_not_errors() -> None:
    window = week_window(date(2027, 1, 25), 0)
    empty = Ratio(0, 0)
    report = LiquidityReport(
        window=window,
        as_of=datetime(2027, 1, 26, 9, tzinfo=UTC),
        overall=Liquidity(),
        pairs=(),
        active_profiles=empty,
        opt_in=Ratio(7, 10),
        repeat_60d=empty,
        k_factor=empty,
        review_rate=empty,
        fraud_reports=empty,
        moderation_sla={},
    )
    text = render(report, week=0)
    assert "неделя 0: 18.01.2027 – 24.01.2027" in text
    assert "Response rate@1h (08:00–22:00): — (0/0)" in text
    assert "Opt-in уведомлений (бот может писать): 70% (7/10)" in text
    assert "заявок за неделю нет" in text
    assert all(f"{name}: {step}" in text for name, step in PENDING.items())


def test_all_weeks_render_one_markdown_table() -> None:
    def week(n: int, rr_1h: Ratio) -> tuple[int, LiquidityReport]:
        empty = Ratio(0, 0)
        report = LiquidityReport(
            window=week_window(date(2027, 1, 25), n),
            as_of=datetime(2027, 2, 3, 9, tzinfo=UTC),
            overall=Liquidity(jobs=rr_1h.total, rr_1h=rr_1h, ttfr_minutes=25.0),
            pairs=(),
            active_profiles=Ratio(3, 10),
            opt_in=empty,
            repeat_60d=empty,
            k_factor=empty,
            review_rate=empty,
            fraud_reports=empty,
        )
        return n, report

    text = render_weeks([week(1, Ratio(3, 4)), week(2, Ratio(0, 0))], beta_start=date(2027, 1, 25))

    assert "Итоги беты «Соседи»: недели 1–2, данные на 03.02.2027 10:00 (Белград)" in text
    table = [line for line in text.splitlines() if line.startswith("|")]
    assert table[0] == "| " + " | ".join(WEEK_COLUMNS) + " |"
    assert table[2].startswith("| 1: 25.01–31.01 | 4 | 75% (3/4) | — (0/0) | — (0/0) | 25 мин |")
    assert table[3].startswith("| 2: 01.02–07.02 | 0 | — (0/0) |")
    assert "| 30% (3/10) |" in table[2]
    assert "Нижний порог пересмотра" in text
    assert render_weeks([], beta_start=date(2027, 1, 25)) == (
        "Бета ещё не началась: неделя 1 — с 25.01.2027, недель для сводки нет."
    )


def test_alert_text_escapes_names() -> None:
    alert = ResponseRateAlert(
        overall=Ratio(3, 10), threshold=0.7, pairs=(("Нови-Сад × <Ремонт>", Ratio(1, 5)),)
    )
    assert "30% (3/10), порог 70%" in alert.text()
    assert "• Нови-Сад × &lt;Ремонт&gt; — 20% (1/5)" in alert.text()
