"""`cli dev-reset-user`: онбординг заново только в dev (DEVELOPMENT_PLAN 1.5b).

Сам сброс на PostgreSQL проверяет интеграционный тест use case (identity); здесь — точка входа:
вне dev команда отказывает, не трогая БД; в dev передаёт Telegram id use case и печатает итог.
"""

from uuid import UUID

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.modules.identity.application.dto import OnboardingReset
from app.platform.kernel.ids import UserId

pytestmark = pytest.mark.unit

USER_ID = UserId(UUID("01a0e259-a46c-75cb-8a6f-c52d857316af"))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Вместо БД — запись вызова: какой Telegram id дошёл до use case."""
    seen: list[int] = []

    async def fake(telegram_id: int) -> OnboardingReset | None:
        seen.append(telegram_id)
        return None if telegram_id == 1 else OnboardingReset(user_id=USER_ID, withdrawn_consents=3)

    monkeypatch.setattr(cli, "_dev_reset_user", fake)
    return seen


@pytest.mark.parametrize("env", ["stage", "production"])
def test_refuses_outside_dev(env: str, calls: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", env)
    result = CliRunner().invoke(cli.app, ["dev-reset-user", "279058397"])
    assert result.exit_code == 1
    assert "only with APP_ENV=dev" in result.output
    assert calls == []


def test_resets_the_user_in_dev(calls: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    result = CliRunner().invoke(cli.app, ["dev-reset-user", "279058397"])
    assert result.exit_code == 0, result.output
    assert calls == [279058397]
    assert f"user {USER_ID}: onboarding reset, 3 consent(s) withdrawn" in result.output


def test_reports_an_unknown_telegram_user(
    calls: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    result = CliRunner().invoke(cli.app, ["dev-reset-user", "1"])
    assert result.exit_code == 1
    assert "no such Telegram user" in result.output
