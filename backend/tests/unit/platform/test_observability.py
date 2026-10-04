"""Наблюдаемость (DEVELOPMENT_PLAN 3.3): экспорт метрик, 429 Telegram, Sentry, heartbeat.

Сеть наружу не нужна: Bot API — сессия-заглушка, Sentry — транспорт в память, Healthchecks —
MockTransport httpx. Сервер метрик слушает свободный порт loopback.
"""

import socket
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
import sentry_sdk
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import User
from dishka import Provider, make_async_container
from prometheus_client import Gauge
from pydantic import SecretStr
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport
from structlog.testing import capture_logs
from typer.testing import CliRunner

from app.entrypoints import cli
from app.interfaces.bot.middlewares import ErrorMiddleware
from app.platform.observability import sentry
from app.platform.observability.metrics import (
    HttpMetrics,
    TelegramMetrics,
    make_registry,
    metrics_server,
)
from app.platform.queue import periodic
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import PeriodicRun, TaskSpec, run_task
from app.platform.settings import HealthchecksSettings, MetricsSettings, Settings
from app.platform.telegram.metrics import FloodWaitMetrics
from app.platform.telegram.texts import BOT_DEFAULTS

pytestmark = pytest.mark.unit

BOT_TOKEN = "8123456789:AAE" + "x" * 32
PING_URL = "https://hc-ping.com/0f5d7c2e-1b2a-4c3d-9e8f-123456789abc"


# --- экспорт метрик -------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_metrics_server_is_off_without_a_port() -> None:
    with metrics_server(MetricsSettings(_env_file=None, port=None), make_registry()):
        pass  # ни потока, ни порта: dev и тесты работают как раньше


def test_metrics_server_serves_the_process_registry_on_its_own_port() -> None:
    registry = make_registry()
    Gauge("sample_gauge", "Sample", registry=registry).set(3)
    port = _free_port()
    settings = MetricsSettings(_env_file=None, port=port, host="127.0.0.1")
    with metrics_server(settings, registry):
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read()
    assert b"sample_gauge 3.0" in body
    with pytest.raises(urllib.error.URLError):  # остановлен вместе с процессом
        urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=1)


def test_http_metrics_bound_method_and_status_labels() -> None:
    registry = make_registry()
    metrics = HttpMetrics(registry)
    metrics.observe(method="GET", route="/api/v1/jobs/{job_id}", status=204, seconds=0.12)
    metrics.observe(method="BREW", route="<unmatched>", status=405, seconds=0.001)

    labels = {"method": "GET", "route": "/api/v1/jobs/{job_id}", "status_class": "2xx"}
    assert registry.get_sample_value("http_requests_total", labels) == 1
    other = {"method": "OTHER", "route": "<unmatched>", "status_class": "4xx"}
    assert registry.get_sample_value("http_requests_total", other) == 1
    bucket = {"method": "GET", "route": "/api/v1/jobs/{job_id}", "le": "0.15"}
    assert registry.get_sample_value("http_request_duration_seconds_bucket", bucket) == 1


# --- 429 Telegram ---------------------------------------------------------------------------


@dataclass
class FloodSession(BaseSession):
    """Сессия Bot API, которая отвечает 429."""

    retry_after: int = 17
    calls: list[TelegramMethod[Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура BaseSession
    ) -> Any:
        self.calls.append(method)
        raise TelegramRetryAfter(method=method, message="Too Many", retry_after=self.retry_after)

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        return None


async def test_every_bot_api_429_is_counted_with_its_retry_after() -> None:
    registry = make_registry()
    session = FloodSession()
    bot = Bot("123456:TEST", session=session, default=BOT_DEFAULTS)
    bot.session.middleware(FloodWaitMetrics(TelegramMetrics(registry)))

    for _ in range(2):
        with pytest.raises(TelegramRetryAfter):  # пауза и повтор — дело отправителя
            await bot(SendMessage(chat_id=42, text="x"))

    labels = {"method": "sendMessage"}
    assert registry.get_sample_value("telegram_rate_limited_total", labels) == 2
    assert registry.get_sample_value("telegram_retry_after_seconds_total", labels) == 34


# --- Sentry ---------------------------------------------------------------------------------


class MemoryTransport(Transport):
    """Транспорт Sentry в память: события не уходят в сеть."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)

    @property
    def events(self) -> list[dict[str, Any]]:
        return [e for envelope in self.envelopes if (e := envelope.get_event()) is not None]


@pytest.fixture
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryTransport]:
    """init_sentry как в процессах, но с транспортом в память; после теста Sentry выключен."""
    transport = MemoryTransport()
    real_init = sentry_sdk.init
    # без интеграций: они патчат FastAPI и stdlib на весь процесс тестов
    monkeypatch.setattr(
        sentry.sentry_sdk,
        "init",
        lambda **options: real_init(
            transport=transport,
            default_integrations=False,
            auto_enabling_integrations=False,
            **options,
        ),
    )
    yield transport
    scope = sentry_sdk.get_global_scope()
    scope.set_client(None)
    scope.remove_tag("process")


def _with_dsn(offline_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.test/1")
    monkeypatch.setenv("APP_RELEASE", "abc123")
    return Settings(env_file=None)


async def test_bot_handler_error_reaches_sentry_masked(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch, sentry_events: MemoryTransport
) -> None:
    assert sentry.init_sentry(_with_dsn(offline_settings, monkeypatch), process="bot")

    async def handler(event: Any, data: dict[str, Any]) -> None:
        raise RuntimeError(f"Bot API refused token {BOT_TOKEN}")

    await ErrorMiddleware()(handler, User(id=1, is_bot=False, first_name="Ана"), {})
    sentry_sdk.flush()

    (event,) = sentry_events.events
    assert BOT_TOKEN not in str(event)
    assert event["tags"]["process"] == "bot"
    assert (event["environment"], event["release"]) == ("dev", "abc123")


async def test_task_error_reaches_sentry_masked(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch, sentry_events: MemoryTransport
) -> None:
    assert sentry.init_sentry(_with_dsn(offline_settings, monkeypatch), process="worker")

    @dataclass(frozen=True, slots=True)
    class Payload:
        phone: str

    async def handler(payload: Payload) -> None:
        raise RuntimeError(f"cannot notify {payload.phone}")

    container = make_async_container(Provider())
    try:
        with pytest.raises(RuntimeError):
            spec = TaskSpec(TaskRef("sample.notify", Payload), handler)
            await run_task(spec, container, {"phone": "+381641234567"}, job_id=1)
    finally:
        await container.close()
    sentry_sdk.flush()

    (event,) = sentry_events.events
    assert "+381641234567" not in str(event)
    assert event["tags"]["process"] == "worker"


def test_cli_sentry_test_sends_an_event_and_prints_its_id(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch, sentry_events: MemoryTransport
) -> None:
    settings = _with_dsn(offline_settings, monkeypatch)
    monkeypatch.setattr(cli, "Settings", lambda: settings)

    result = CliRunner().invoke(cli.app, ["sentry-test"])

    assert result.exit_code == 0, result.output
    (event,) = sentry_events.events
    assert event["event_id"] in result.output
    assert event["exception"]["values"][0]["type"] == "SentryTestError"
    assert event["tags"]["process"] == "cli"


def test_cli_sentry_test_without_dsn_only_explains(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch, sentry_events: MemoryTransport
) -> None:
    monkeypatch.setattr(cli, "Settings", lambda: offline_settings)

    result = CliRunner().invoke(cli.app, ["sentry-test"])

    assert result.exit_code == 1
    assert "SENTRY_DSN не задан" in result.output
    assert sentry_events.envelopes == []


# --- heartbeat Healthchecks -----------------------------------------------------------------


@dataclass
class SettingsContainer:
    healthchecks: HealthchecksSettings

    async def get(self, tp: type[Any]) -> Any:
        assert tp is HealthchecksSettings
        return self.healthchecks


def _heartbeat_run(url: str | None) -> PeriodicRun:
    ping = SecretStr(url) if url else None
    container = SettingsContainer(HealthchecksSettings(_env_file=None, worker_ping_url=ping))
    return PeriodicRun(app=cast(Any, None), container=cast(Any, container), timestamp=0)


@pytest.fixture
def pings(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Запросы heartbeat к Healthchecks — в список; ответ 200, а для /missing — 404."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404 if request.url.path.endswith("/missing") else 200)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        periodic.httpx,
        "AsyncClient",
        lambda **options: real_client(transport=httpx.MockTransport(answer), **options),
    )
    return requests


async def test_heartbeat_without_ping_url_only_logs(pings: list[httpx.Request]) -> None:
    await periodic.heartbeat(_heartbeat_run(None))
    assert pings == []


async def test_heartbeat_pings_healthchecks(pings: list[httpx.Request]) -> None:
    await periodic.heartbeat(_heartbeat_run(PING_URL))
    assert [str(request.url) for request in pings] == [PING_URL]


async def test_failed_ping_is_logged_without_the_url(pings: list[httpx.Request]) -> None:
    with capture_logs() as logs:
        await periodic.heartbeat(_heartbeat_run("https://hc-ping.com/missing"))
    failed = [entry for entry in logs if entry["event"] == "heartbeat_ping_failed"]
    assert failed == [
        {"event": "heartbeat_ping_failed", "error": "HTTPStatusError", "log_level": "warning"}
    ]
