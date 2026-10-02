"""`cli reindex --all`: пересборка read-model поиска (DEVELOPMENT_PLAN 4.1). Сама пересборка —
в интеграционном тесте read-model; здесь — точка входа."""

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._search_cli import ReindexReport

pytestmark = pytest.mark.unit


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def fake() -> ReindexReport:
        seen.append("reindex")
        return ReindexReport(published=60, indexed_before=58, rebuilt=60, removed=1)

    monkeypatch.setattr(cli, "_reindex", fake)
    return seen


def test_reindex_all_reports_what_it_did(runs: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["reindex", "--all"])

    assert result.exit_code == 0, result.output
    assert "60 published, 58 rows before; 60 rebuilt, 1 removed" in result.output
    assert runs == ["reindex"]


def test_reindex_needs_the_all_flag(runs: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["reindex"])

    assert result.exit_code == 2
    assert runs == []
