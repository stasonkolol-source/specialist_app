"""Аналитика (DEVELOPMENT_PLAN 1.7): таксономия против PRODUCT и плана, свойства без ПД,
адаптер PostHog EU."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.modules.growth.domain.attribution import AttributionSource
from app.modules.identity.domain.user import UserIntent
from app.modules.notifications.domain.channel import GrantedVia
from app.platform.analytics.events import (
    ENTRY_POINTS,
    EVENTS,
    INTENTS,
    METRICS,
    NORTH_STAR,
    WRITE_ACCESS_VIA,
    EventName,
    analytics_event,
)
from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import AnalyticsEvent
from app.platform.analytics.posthog import PostHogAnalytics
from app.platform.contracts.events.identity import EntryPoint
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.kernel.ids import new_id
from app.platform.telegram.deeplinks import LinkSource

pytestmark = pytest.mark.unit

DOCS = Path(__file__).resolve().parents[4] / "docs"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
METRIC_SECTIONS = ("Ликвидность", "Стороны и удержание", "Доверие и качество", "Бизнес")


def product_metrics() -> set[str]:
    """Первая колонка таблиц «Метрики успеха» PRODUCT.md (без ворот go / no-go)."""
    text = (DOCS / "PRODUCT.md").read_text(encoding="utf-8")
    section = text.split("## Метрики успеха", 1)[1].split("### Ворота и go / no-go", 1)[0]
    names: set[str] = set()
    for block in re.split(r"^### ", section, flags=re.M)[1:]:
        if not block.startswith(METRIC_SECTIONS):
            continue
        for line in block.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if (
                line.startswith("|")
                and cells[0] not in {"Метрика"}
                and not cells[0].startswith("-")
            ):
                names.add(cells[0])
    return names


def test_taxonomy_covers_every_product_metric() -> None:
    assert {m.name for m in METRICS} == product_metrics()
    assert "`deals.completed`" in (DOCS / "PRODUCT.md").read_text(encoding="utf-8")
    assert NORTH_STAR.name == "deals.completed"


def test_every_metric_has_a_source_step_and_known_events() -> None:
    for metric in (*METRICS, NORTH_STAR):
        assert re.fullmatch(r"\d+\.\d+[a-z]?|v1", metric.step), metric.name
        assert metric.events or metric.source != "события", metric.name
        assert set(metric.events) <= set(EVENTS), metric.name


def test_taxonomy_lists_exactly_the_events_of_the_plan() -> None:
    plan = (DOCS / "DEVELOPMENT_PLAN.md").read_text(encoding="utf-8")
    step = plan.split("### 1.7.", 1)[1].split("\n### ", 1)[0]
    backend = next(line for line in step.splitlines() if line.startswith("- **Backend.**"))
    events = backend.split("Здесь подключаются", 1)[1]  # до этого — `distinct_id` и пр.
    names = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", events))
    assert names == {e.value for e in EventName}


def test_wired_events_are_those_of_step_1_7() -> None:
    wired = {name for name, spec in EVENTS.items() if spec.properties is not None}
    assert wired == {
        EventName.USER_REGISTERED,
        EventName.ONBOARDING_COMPLETED,
        EventName.WRITE_ACCESS_GRANTED,
    }
    assert all(EVENTS[name].step == "1.7" for name in wired)


def test_closed_lists_match_the_domain() -> None:
    assert {s.value for s in LinkSource} == {s.value for s in AttributionSource}
    assert {i.value for i in UserIntent} | {"unknown"} == INTENTS
    assert {e.value for e in EntryPoint} | {"unknown"} == ENTRY_POINTS
    assert {v.value for v in GrantedVia} == WRITE_ACCESS_VIA


def registered(**properties: Any) -> AnalyticsEvent:
    return analytics_event(
        EventName.USER_REGISTERED,
        user_id=new_id(),
        occurred_at=NOW,
        source_event_id=new_id(),
        **properties,
    )


def test_event_carries_only_allowed_values() -> None:
    event = registered(source="specialist", entry_point="bot", has_referral=True)

    assert event.name == "user_registered"
    assert dict(event.properties) == {
        "source": "specialist",
        "entry_point": "bot",
        "has_referral": True,
    }


@pytest.mark.parametrize(
    "properties",
    [
        {"first_name": "Ana"},  # поля, которого нет в схеме
        {"source": "Ana Petrović"},  # свободный текст вместо значения из списка
        {"source": "+381641234567"},
        {"source": "ana@example.com"},
        {"entry_point": "@ana_ns"},
        {"has_referral": "yes"},  # не флаг
    ],
    ids=["unknown-field", "name", "phone", "email", "username", "not-a-flag"],
)
def test_personal_data_cannot_become_a_property(properties: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="user_registered"):
        registered(**properties)


def test_city_is_a_reference_id_not_text() -> None:
    def onboarded(**properties: Any) -> AnalyticsEvent:
        return analytics_event(
            EventName.ONBOARDING_COMPLETED,
            user_id=new_id(),
            occurred_at=NOW,
            source_event_id=new_id(),
            **properties,
        )

    assert onboarded(intent="pro", city=1).properties["city"] == 1
    for bad in ({"city": "Нови-Сад"}, {"city": 0}, {"city": True}, {"intent": "PRO"}):
        with pytest.raises(ValueError, match="onboarding_completed"):
            onboarded(**bad)


def test_declared_but_not_wired_event_is_refused() -> None:
    with pytest.raises(ValueError, match="not wired yet"):
        analytics_event(
            EventName.JOB_PUBLISHED, user_id=new_id(), occurred_at=NOW, source_event_id=new_id()
        )


def test_same_domain_event_gives_same_analytics_id() -> None:
    user_id, source = new_id(), new_id()

    def once() -> AnalyticsEvent:
        return analytics_event(
            EventName.WRITE_ACCESS_GRANTED,
            user_id=user_id,
            occurred_at=NOW,
            source_event_id=source,
            via="bot_start",
        )

    assert once().event_id == once().event_id
    assert once().event_id != registered(source="organic").event_id


# --- PostHog -----------------------------------------------------------------------------


def posthog(handler: Any) -> PostHogAnalytics:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PostHogAnalytics(
        client, api_key=SecretStr("phc_test"), host="https://eu.i.posthog.com/", environment="dev"
    )


async def test_posthog_payload_has_no_device_or_ip() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": 1})

    event = registered(source="home", entry_point="mini_app", has_referral=False)
    await posthog(handler).capture(event)

    [request] = requests
    body = json.loads(request.content)
    assert str(request.url) == "https://eu.i.posthog.com/i/v0/e/"
    assert body == {
        "api_key": "phc_test",
        "event": "user_registered",
        "distinct_id": str(event.distinct_id),
        "uuid": str(event.event_id),
        "timestamp": "2026-10-05T09:00:00+00:00",
        "properties": {
            "source": "home",
            "entry_point": "mini_app",
            "has_referral": False,
            "environment": "dev",
            "$lib": "sosedi-backend",
            "$geoip_disable": True,
        },
    }


async def test_posthog_server_errors_are_retried() -> None:
    event = registered(source="organic")

    with pytest.raises(ExternalServiceError):
        await posthog(lambda _: httpx.Response(503)).capture(event)

    def offline(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with pytest.raises(ExternalServiceError):
        await posthog(offline).capture(event)


async def test_posthog_rate_limit_waits_retry_after() -> None:
    limited = posthog(lambda _: httpx.Response(429, headers={"Retry-After": "42"}))

    with pytest.raises(RateLimitedError) as caught:
        await limited.capture(registered(source="organic"))
    assert caught.value.retry_after == 42


async def test_posthog_rejection_is_not_retried() -> None:
    """Неверный ключ повтором не лечится: ошибка в лог и Sentry, задача не падает."""
    await posthog(lambda _: httpx.Response(401)).capture(registered(source="organic"))


async def test_logging_fake_writes_event_to_log() -> None:
    """dev без ключа PostHog (K32): регистрацию и онбординг видно в логе воркера."""
    fake = LoggingAnalytics()
    event = registered(source="legal", entry_point="bot", has_referral=False)

    with capture_logs() as logs:
        await fake.capture(event)

    assert fake.captured == [event]
    assert logs == [
        {
            "event": "analytics_event",
            "log_level": "info",
            "name": "user_registered",
            "user_id": str(event.distinct_id),
            "properties": {"source": "legal", "entry_point": "bot", "has_referral": False},
        }
    ]
