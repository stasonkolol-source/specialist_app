"""`cli bot-setup --env <env>` (DEVELOPMENT_PLAN 1.6, 0.25e): на фейковом Bot API — webhook с
секретом и узким allowed_updates в режиме webhook, снятие webhook в режиме polling; без секрета
или https команда отказывает до первого вызова Telegram. Секрет в вывод не попадает."""

from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import (
    DeleteWebhook,
    GetChatMenuButton,
    GetMe,
    GetMyCommands,
    GetMyDescription,
    GetMyName,
    GetMyShortDescription,
    GetWebhookInfo,
    SetWebhook,
    TelegramMethod,
)
from aiogram.types import (
    BotDescription,
    BotName,
    BotShortDescription,
    MenuButtonDefault,
    User,
    WebhookInfo,
)
from typer.testing import CliRunner

from app.entrypoints import cli
from app.interfaces.bot.app import ALLOWED_UPDATES
from app.platform.settings import AppSettings, TelegramSettings

pytestmark = pytest.mark.unit

TOKEN = "7000000002:TEST_ONLY_synthetic_bot_token"  # noqa: S105 — синтетический
SECRET = "f" * 64  # синтетический, как make gen-secret: 32 байта в hex


class FakeBotApi:
    """Bot API без сети: профиль пуст, кнопка меню — по умолчанию, webhook — `webhook_url`."""

    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура BaseSession
    ) -> Any:
        self.calls.append(method)
        match method:
            case GetMe():
                return User(id=1, is_bot=True, first_name="Sosedi", username="sosed_stage_bot")
            case GetMyName():
                return BotName(name="")
            case GetMyDescription():
                return BotDescription(description="")
            case GetMyShortDescription():
                return BotShortDescription(short_description="")
            case GetMyCommands():
                return []
            case GetChatMenuButton():
                return MenuButtonDefault()
            case GetWebhookInfo():
                return WebhookInfo(
                    url=self.webhook_url, has_custom_certificate=False, pending_update_count=3
                )
            case SetWebhook():
                self.webhook_url = method.url
            case DeleteWebhook():
                self.webhook_url = ""
        return True

    def sent(self, kind: type[TelegramMethod[Any]]) -> list[Any]:
        return [call for call in self.calls if isinstance(call, kind)]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeBotApi:
    fake = FakeBotApi()
    monkeypatch.setattr(AiohttpSession, "make_request", fake.make_request)
    # только окружение теста: backend/.env разработчика не подмешивается
    for group in (AppSettings, TelegramSettings):
        monkeypatch.setitem(group.model_config, "env_file", None)
    for name, value in {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_BOT_USERNAME": "sosed_stage_bot",
        "TELEGRAM_MINI_APP_URL": "https://stage-app.example.test",
    }.items():
        monkeypatch.setenv(name, value)
    for name in (
        "TELEGRAM_UPDATES",
        "TELEGRAM_WEBHOOK_SECRET",
        "TELEGRAM_WEBHOOK_BASE_URL",
        "APP_API_PUBLIC_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture
def stage_webhook(api: FakeBotApi, monkeypatch: pytest.MonkeyPatch) -> FakeBotApi:
    monkeypatch.setenv("APP_ENV", "stage")
    monkeypatch.setenv("TELEGRAM_UPDATES", "webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("APP_API_PUBLIC_URL", "https://stage-api.example.test")
    # свой хост бота: kamal-proxy не отдаёт stage-api с TLS второй роли
    monkeypatch.setenv("TELEGRAM_WEBHOOK_BASE_URL", "https://stage-bot.example.test")
    return api


def test_webhook_mode_sets_the_webhook_with_the_secret(stage_webhook: FakeBotApi) -> None:
    result = CliRunner().invoke(cli.app, ["bot-setup", "--env", "stage"])

    assert result.exit_code == 0, result.output
    [call] = stage_webhook.sent(SetWebhook)
    assert call.url == "https://stage-bot.example.test/integrations/telegram/webhook"
    assert call.secret_token == SECRET
    assert call.allowed_updates == list(ALLOWED_UPDATES)
    assert call.drop_pending_updates is False
    assert stage_webhook.sent(DeleteWebhook) == []
    assert (
        "@sosed_stage_bot: webhook set → https://stage-bot.example.test/integrations/telegram/"
        "webhook [message, callback_query, my_chat_member], pending 3"
    ) in result.output
    assert "menu button set → https://stage-app.example.test" in result.output
    assert SECRET not in result.output


def test_without_a_bot_host_the_webhook_goes_to_the_api_address(
    stage_webhook: FakeBotApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_WEBHOOK_BASE_URL")

    result = CliRunner().invoke(cli.app, ["bot-setup", "--env", "stage"])

    assert result.exit_code == 0, result.output
    [call] = stage_webhook.sent(SetWebhook)
    assert call.url == "https://stage-api.example.test/integrations/telegram/webhook"


def test_rerun_sets_the_webhook_again(stage_webhook: FakeBotApi) -> None:
    """Секрет у Telegram не прочитать: повтор (например, после ротации) ставит webhook заново."""
    for _ in range(2):
        assert CliRunner().invoke(cli.app, ["bot-setup", "--env", "stage"]).exit_code == 0

    assert len(stage_webhook.sent(SetWebhook)) == 2


def test_polling_mode_removes_a_webhook(api: FakeBotApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    api.webhook_url = "https://old.example.test/integrations/telegram/webhook"

    result = CliRunner().invoke(cli.app, ["bot-setup", "--env", "dev"])

    assert result.exit_code == 0, result.output
    assert [call.drop_pending_updates for call in api.sent(DeleteWebhook)] == [False]
    assert api.sent(SetWebhook) == []
    assert "@sosed_stage_bot: webhook deleted (polling)" in result.output


def test_polling_mode_without_a_webhook_changes_nothing(
    api: FakeBotApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")

    result = CliRunner().invoke(cli.app, ["bot-setup", "--env", "dev"])

    assert result.exit_code == 0, result.output
    assert api.sent(DeleteWebhook) == []
    assert "no webhook (polling)" in result.output


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("TELEGRAM_WEBHOOK_SECRET", None, "не задан TELEGRAM_WEBHOOK_SECRET"),
        ("TELEGRAM_WEBHOOK_SECRET", "short", "TELEGRAM_WEBHOOK_SECRET: нужно 32–256"),
        ("TELEGRAM_WEBHOOK_BASE_URL", "http://stage-bot.example.test", "только https://"),
        ("TELEGRAM_WEBHOOK_BASE_URL", "https://stage-bot.example.test/bot", "без пути"),
    ],
)
def test_webhook_mode_refuses_before_any_bot_api_call(
    stage_webhook: FakeBotApi,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str | None,
    message: str,
) -> None:
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)

    result = CliRunner().invoke(cli.app, ["bot-setup", "--env", "stage"])

    assert result.exit_code == 1
    assert message in result.output
    assert stage_webhook.calls == []
