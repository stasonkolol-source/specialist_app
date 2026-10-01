"""`cli dev-initdata`: initData dev-бота проходит проверку; вне dev команда отказывает."""

from urllib.parse import parse_qs, urlsplit

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


def test_dev_initdata_has_the_signature_field_the_mini_app_sdk_needs(
    dev_env: pytest.MonkeyPatch,
) -> None:
    result = CliRunner().invoke(cli.app, ["dev-initdata"])
    assert "signature=dev" in result.output  # без поля SDK не признаёт параметры запуска


def test_dev_initdata_url_opens_the_stand_in_a_browser(dev_env: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli.app, ["dev-initdata", "--url", "--language", "sr"])
    assert result.exit_code == 0, result.output
    url = urlsplit(result.output.strip())
    query = parse_qs(url.query)
    assert (url.netloc, query["platform"], query["lang"]) == ("localhost:5173", ["mock"], ["sr"])
    data = InitDataVerifier(SecretStr(TOKEN), SystemClock()).verify(query["initData"][0])
    assert data.user.id == 100000001


def test_dev_initdata_refuses_outside_dev(dev_env: pytest.MonkeyPatch) -> None:
    dev_env.setenv("APP_ENV", "production")
    result = CliRunner().invoke(cli.app, ["dev-initdata"])
    assert result.exit_code == 1
    assert "hash=" not in result.output
