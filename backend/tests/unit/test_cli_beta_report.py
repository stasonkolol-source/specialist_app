"""`cli beta-report`: неделя или скользящее окно (DEVELOPMENT_PLAN 6.6). Сами метрики — в
`tests/integration/test_liquidity_metrics.py`; здесь — разбор аргументов точки входа."""

from datetime import date

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.platform.settings import AnalyticsSettings

pytestmark = pytest.mark.unit


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    seen: list[tuple[str, object]] = []

    async def week(week: int | None, beta_start: date | None) -> str:
        seen.append(("week", (week, beta_start)))
        return "weekly"

    async def rolling(last: str) -> str:
        seen.append(("last", last))
        return "rolling"

    monkeypatch.setattr(cli, "_beta_report", week)
    monkeypatch.setattr(cli, "_rolling_report", rolling)
    return seen


def test_week_or_rolling_window(calls: list[tuple[str, object]]) -> None:
    runner = CliRunner()
    weekly = runner.invoke(cli.app, ["beta-report", "--week", "1", "--start", "2026-10-12"])
    day = runner.invoke(cli.app, ["beta-report", "--last", "24h"])
    seven = runner.invoke(cli.app, ["beta-report", "--last", "7d"])

    assert (weekly.exit_code, day.exit_code, seven.exit_code) == (0, 0, 0)
    assert (weekly.output, day.output) == ("weekly\n", "rolling\n")
    assert calls == [("week", (1, date(2026, 10, 12))), ("last", "24h"), ("last", "7d")]


@pytest.mark.parametrize(
    "args",
    [[], ["--week", "1", "--last", "24h"], ["--last", "30d"], ["--week", "first"]],
)
def test_needs_exactly_one_period(calls: list[tuple[str, object]], args: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["beta-report", *args])

    assert result.exit_code == 2
    assert calls == []


def test_beta_starts_with_the_first_production_release() -> None:
    """Неделя 1 по умолчанию — с понедельника первого релиза прода, а не с ориентира плана."""
    assert AnalyticsSettings.model_fields["beta_start"].default == date(2026, 10, 12)
