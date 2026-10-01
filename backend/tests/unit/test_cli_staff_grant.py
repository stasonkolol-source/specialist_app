"""`cli staff-grant`: выдача роли персонала (DEVELOPMENT_PLAN 2.5a).

Саму выдачу на PostgreSQL проверяет интеграционный тест use case (identity); здесь — точка
входа: роль из списка, Telegram id доходит до use case, итог и отказ печатаются.
"""

from uuid import UUID

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.modules.identity.application.dto import StaffRoleGranted
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Role

pytestmark = pytest.mark.unit

USER_ID = UserId(UUID("01a0e259-a46c-75cb-8a6f-c52d857316af"))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    seen: list[tuple[int, str]] = []

    async def fake(telegram_id: int, role: str) -> StaffRoleGranted | None:
        seen.append((telegram_id, role))
        if telegram_id == 1:
            return None
        return StaffRoleGranted(user_id=USER_ID, role=Role(role), granted=telegram_id != 2)

    monkeypatch.setattr(cli, "_staff_grant", fake)
    return seen


def grant(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(cli.app, ["staff-grant", *args])
    return result.exit_code, result.output


def test_grants_a_role_by_telegram_id(calls: list[tuple[int, str]]) -> None:
    code, output = grant("--tg-id", "279058397", "--role", "moderator")

    assert code == 0, output
    assert calls == [(279058397, "moderator")]
    assert f"user {USER_ID}: role moderator granted" in output
    assert "already granted" in grant("--tg-id", "2", "--role", "admin")[1]


def test_unknown_user_and_role_are_refused(calls: list[tuple[int, str]]) -> None:
    code, output = grant("--tg-id", "1", "--role", "support")
    assert code == 1
    assert "no such Telegram user" in output

    assert grant("--tg-id", "279058397", "--role", "owner")[0] == 2  # не роль — ошибка typer
    assert calls == [(1, "support")]
