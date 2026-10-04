"""`cli loadtest-initdata` (8.3): initData демо-специалистов для k6 — проходит проверку токеном
бота окружения; на проде команда отказывает."""

import json

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._seed_demo import DEMO_TELEGRAM_BASE, plan
from app.platform.kernel.clock import SystemClock
from app.platform.security.initdata import InitDataVerifier

pytestmark = pytest.mark.unit

TOKEN = "7000000001:TEST_ONLY_synthetic_bot_token"  # noqa: S105 — синтетический


@pytest.fixture
def stage_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("APP_ENV", "stage")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "sosed_test_bot")
    return monkeypatch


def test_batch_logs_in_as_seeded_demo_specialists(stage_env: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli.app, ["loadtest-initdata", "--count", "3", "--start", "10"])

    assert result.exit_code == 0, result.output
    batch = json.loads(result.output)
    verifier = InitDataVerifier(SecretStr(TOKEN), SystemClock())
    users = [verifier.verify(raw).user for raw in batch]
    assert [user.id for user in users] == [DEMO_TELEGRAM_BASE + n for n in (10, 11, 12)]
    # те же имя и язык, что у сида: вход не переписывает демо-профиль
    assert (users[0].first_name, users[0].language_code) == (plan(10).first_name, plan(10).lang)


def test_refuses_production(stage_env: pytest.MonkeyPatch) -> None:
    stage_env.setenv("APP_ENV", "production")

    result = CliRunner().invoke(cli.app, ["loadtest-initdata", "--count", "1"])

    assert result.exit_code == 1
    assert "hash=" not in result.output
