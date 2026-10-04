"""`cli staff-revoke`: закрыть сессии админки сотрудника (2.7b, ревью безопасности).

Само закрытие на PostgreSQL проверяет интеграционный тест админки (test_admin_auth.py); здесь —
точка входа: Telegram id и `--remove-login` доходят до use case, итог и отказ печатаются.
"""

from uuid import UUID

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.modules.identity.application.dto import StaffSessionsRevoked
from app.platform.kernel.ids import UserId

pytestmark = pytest.mark.unit

USER_ID = UserId(UUID("01a0e259-a46c-75cb-8a6f-c52d857316af"))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    seen: list[tuple[int, bool]] = []

    async def fake(telegram_id: int, *, remove_login: bool) -> StaffSessionsRevoked | None:
        seen.append((telegram_id, remove_login))
        if telegram_id == 1:
            return None
        return StaffSessionsRevoked(user_id=USER_ID, login_removed=remove_login)

    monkeypatch.setattr(cli, "_staff_revoke", fake)
    return seen


def revoke(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(cli.app, ["staff-revoke", *args])
    return result.exit_code, result.output


def test_revokes_sessions_and_optionally_the_login(calls: list[tuple[int, bool]]) -> None:
    code, output = revoke("--tg-id", "279058397")
    assert code == 0, output
    assert f"user {USER_ID}: admin sessions revoked" in output
    assert "login removed" not in output

    code, output = revoke("--tg-id", "279058397", "--remove-login")
    assert code == 0, output
    assert "admin sessions revoked, login removed" in output
    assert calls == [(279058397, False), (279058397, True)]


def test_unknown_user_or_login_is_refused(calls: list[tuple[int, bool]]) -> None:
    code, output = revoke("--tg-id", "1")
    assert code == 1
    assert "no such Telegram user or no admin login" in output
