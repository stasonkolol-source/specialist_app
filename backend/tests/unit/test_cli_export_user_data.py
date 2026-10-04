"""`cli export-user-data`: выгрузка данных пользователя (DEVELOPMENT_PLAN 2.12b). Разделы модулей
и audit_log — в tests/integration/test_retention.py; здесь — точка входа."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from app.entrypoints import _export_cli, cli

pytestmark = pytest.mark.unit

USER = "01a0e259-a46c-75cb-8a6f-c52d857316af"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    seen: list[tuple[str, str | None]] = []

    async def fake(user_ref: str, *, note: str | None) -> dict[str, Any] | None:
        seen.append((user_ref, note))
        if user_ref == "1":
            return None
        return {"format": 1, "user_id": USER, "sections": {"identity": {}, "jobs": {}}}

    monkeypatch.setattr(_export_cli, "export_user_data", fake)
    return seen


def test_writes_file_and_reports_sections(
    calls: list[tuple[str, str | None]], tmp_path: Path
) -> None:
    target = tmp_path / "export.json"
    runner = CliRunner()
    written = runner.invoke(
        cli.app, ["export-user-data", USER, "--output", str(target), "--note", "ticket-7"]
    )
    printed = runner.invoke(cli.app, ["export-user-data", "279058397"])
    missing = runner.invoke(cli.app, ["export-user-data", "1"])

    assert (written.exit_code, printed.exit_code, missing.exit_code) == (0, 0, 1)
    assert json.loads(target.read_text(encoding="utf-8"))["user_id"] == USER
    assert "sections: identity, jobs" in written.output
    assert json.loads(printed.output)["user_id"] == USER
    assert "no such user" in missing.output
    assert calls == [(USER, "ticket-7"), ("279058397", None), ("1", None)]
