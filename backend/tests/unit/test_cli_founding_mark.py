"""`cli founding-mark`: статус Founding профилю (DEVELOPMENT_PLAN 2.8a). Сам use case — в
интеграционном тесте specialists; здесь — точка входа."""

from uuid import UUID

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.modules.specialists.application.use_cases.mark_founding import FoundingMarked
from app.modules.specialists.domain.profile import ProfileId

pytestmark = pytest.mark.unit

PROFILE = ProfileId(UUID("01a0e259-a46c-75cb-8a6f-c52d857316af"))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []

    async def fake(telegram_id: int) -> FoundingMarked | None:
        seen.append(telegram_id)
        return (
            None
            if telegram_id == 1
            else FoundingMarked(profile_id=PROFILE, marked=telegram_id != 2)
        )

    monkeypatch.setattr(cli, "_founding_mark", fake)
    return seen


def test_marks_and_reports(calls: list[int]) -> None:
    runner = CliRunner()
    marked = runner.invoke(cli.app, ["founding-mark", "--tg-id", "279058397"])
    again = runner.invoke(cli.app, ["founding-mark", "--tg-id", "2"])
    missing = runner.invoke(cli.app, ["founding-mark", "--tg-id", "1"])

    assert (marked.exit_code, again.exit_code, missing.exit_code) == (0, 0, 1)
    assert f"profile {PROFILE}: founding marked" in marked.output
    assert "already marked" in again.output
    assert "no specialist profile" in missing.output
    assert calls == [279058397, 2, 1]
