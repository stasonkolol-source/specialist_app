"""`cli notify-test` (DEVELOPMENT_PLAN 2.3b): точка входа.

Конвейер до вызова Bot API проверяет интеграционный тест notifications
(test_channel_status.py); здесь — что команда передаёт пользователя и как сообщает итог.
"""

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._notify_test import NotifyTestOutcome

pytestmark = pytest.mark.unit


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def fake(user_ref: str) -> NotifyTestOutcome:
        seen.append(user_ref)
        if user_ref == "404":
            return NotifyTestOutcome(sent=False, message="notify-test: no such user 404")
        return NotifyTestOutcome(sent=True, message="user x: sent")

    monkeypatch.setattr(cli, "_notify_test", fake)
    return seen


def test_sends_to_the_user(calls: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["notify-test", "--user", "279058397"])

    assert result.exit_code == 0, result.output
    assert calls == ["279058397"]
    assert "user x: sent" in result.output


def test_fails_when_nothing_was_sent(calls: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["notify-test", "--user", "404"])

    assert result.exit_code == 1
    assert "no such user 404" in result.output
