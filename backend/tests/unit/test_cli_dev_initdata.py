"""`cli dev-initdata`: initData dev-бота проходит проверку; вне dev команда отказывает."""

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from app.entrypoints import cli
from app.platform.kernel.clock import SystemClock
from app.platform.security.initdata import InitDataVerifier

pytestmark = pytest.mark.unit

TOKEN = "7000000001:TEST_ONLY_synthetic_bot_token"  # noqa: S105 — синтетический


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "sosed_test_bot")
    return monkeypatch


def test_dev_initdata_is_valid_for_dev_bot(dev_env: pytest.MonkeyPatch) -> None:
    args = ["dev-initdata", "--user-id", "42", "--first-name", "Ана", "--start-param", "job_x"]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    data = InitDataVerifier(SecretStr(TOKEN), SystemClock()).verify(result.output.strip())
    assert (data.user.id, data.user.first_name, data.start_param) == (42, "Ана", "job_x")


def test_dev_initdata_refuses_outside_dev(dev_env: pytest.MonkeyPatch) -> None:
    dev_env.setenv("APP_ENV", "production")
    result = CliRunner().invoke(cli.app, ["dev-initdata"])
    assert result.exit_code == 1
    assert "hash=" not in result.output
