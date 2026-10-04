"""Аналитика (DEVELOPMENT_PLAN 1.7): таксономия против PRODUCT и плана, свойства без ПД,
адаптер PostHog EU."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs

from app.modules.deals.domain.deal import MODERATOR, SYSTEM, DealCancelReason, DealOrigin, DealRole
from app.modules.deals.domain.dispute import DisputeKind
from app.modules.growth.api import ShareTarget
from app.modules.growth.domain.attribution import AttributionSource
from app.modules.identity.domain.user import UserIntent
from app.modules.jobs.domain.alert import AlertDelivery
from app.modules.jobs.domain.job import CloseReason, Urgency
from app.modules.messaging.domain.conversation import ConversationKind, ParticipantRole
from app.modules.messaging.domain.message import ContactType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import REASONS, ReportReason, report_queue
from app.modules.notifications.domain.channel import GrantedVia
from app.platform.analytics.events import (
    ALERT_DELIVERIES,
    CLOSE_REASONS,
    CONTACT_TYPES,
    CONVERSATION_KINDS,
    DEAL_CANCEL_REASONS,
    DEAL_CANCELLED_BY,
    DEAL_ORIGINS,
    DEAL_ROLES,
    DISPUTE_KINDS,
    ENTRY_POINTS,
    EVENTS,
    INTENTS,
    METRICS,
    NORTH_STAR,
    REPORT_QUEUES,
    REPORT_REASONS,
    REPORT_TARGETS,
    SHARE_ENTITIES,
    URGENCIES,
    WRITE_ACCESS_VIA,
    EventName,
    analytics_event,
)
from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import AnalyticsEvent
from app.platform.analytics.posthog import PostHogAnalytics
from app.platform.analytics.tasks import (
    capture_alert_created,
    capture_alerts_matched,
    capture_attribution_recorded,
    capture_contact_shared,
    capture_conversation_started,
    capture_deal_agreed,
    capture_deal_cancelled,
    capture_goods_waitlist_joined,
    capture_job_invited,
    capture_message_sent,
    capture_onboarding_completed,
    capture_report_created,
    capture_share_created,
    capture_write_access_granted,
)
from app.platform.contracts.events.deals import DealAgreed, DealCancelled
from app.platform.contracts.events.growth import AttributionRecorded, ShareCreated
from app.platform.contracts.events.identity import EntryPoint, OnboardingCompleted
from app.platform.contracts.events.jobs import AlertCreated, AlertsMatched, JobInvited
from app.platform.contracts.events.messaging import ContactShared, ConversationStarted, MessageSent
from app.platform.contracts.events.moderation import ReportCreated
from app.platform.contracts.events.notifications import GoodsWaitlistJoined, WriteAccessGranted
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.kernel.ids import CaseId, CategoryId, CityId, DealId, UserId, new_id
from app.platform.settings import AnalyticsSettings
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


def test_wired_events_are_those_of_the_finished_steps() -> None:
    wired = {name: spec.step for name, spec in EVENTS.items() if spec.properties is not None}
    assert wired == {
        EventName.USER_REGISTERED: "1.7",
        EventName.ONBOARDING_COMPLETED: "1.7",
        EventName.WRITE_ACCESS_GRANTED: "1.7",
        EventName.PROFILE_SUBMITTED: "2.8a",
        EventName.PROFILE_PUBLISHED: "2.8a",
        EventName.JOB_PUBLISHED: "5.1",
        EventName.JOB_CLOSED: "5.1",
        EventName.JOB_EXPIRED: "5.1",
        EventName.RESPONSE_SUBMITTED: "5.4",
        EventName.INVITE_SENT: "5.6",
        EventName.DIRECT_REQUEST_SENT: "5.6",
        EventName.DEAL_AGREED: "6.1a",
        EventName.DEAL_COMPLETED: "6.1a",
        EventName.DEAL_CANCELLED: "6.1a",
        EventName.DISPUTE_OPENED: "6.1c",
        EventName.CONVERSATION_STARTED: "6.3a",
        EventName.MESSAGE_SENT: "6.3a",
        EventName.CONTACT_SHARED: "6.3b",
        EventName.REVIEW_PUBLISHED: "7.2",
        EventName.REPORT_CREATED: "4.7",
        EventName.SHARE_CREATED: "7.4",
        EventName.ATTRIBUTION_RECORDED: "7.4",
        EventName.ALERT_CREATED: "5.7",
        EventName.JOB_MATCHED_NOTIFIED: "5.7",
        EventName.GOODS_WAITLIST_JOINED: "7.5",
    }


def test_closed_lists_match_the_domain() -> None:
    assert {s.value for s in LinkSource} == {s.value for s in AttributionSource}
    assert {i.value for i in UserIntent} | {"unknown"} == INTENTS
    assert {e.value for e in EntryPoint} | {"unknown"} == ENTRY_POINTS
    assert {v.value for v in GrantedVia} == WRITE_ACCESS_VIA
    assert {u.value for u in Urgency} == URGENCIES
    assert {r.value for r in CloseReason} == CLOSE_REASONS
    assert {r.value for r in DealRole} == DEAL_ROLES
    assert {o.value for o in DealOrigin} == DEAL_ORIGINS
    assert {r.value for r in DealRole} | {SYSTEM, MODERATOR} == DEAL_CANCELLED_BY
    assert {r.value for r in DealCancelReason} == DEAL_CANCEL_REASONS
    assert {k.value for k in DisputeKind} == DISPUTE_KINDS
    assert {k.value for k in ConversationKind} - {"support"} == CONVERSATION_KINDS
    assert {r.value for r in ParticipantRole} - {"support"} == DEAL_ROLES
    assert {t.value for t in ContactType} == CONTACT_TYPES
    assert {r.value for r in ReportReason} == REPORT_REASONS
    assert {t.value for t in REASONS} == REPORT_TARGETS
    assert {report_queue(r).value for r in ReportReason} == REPORT_QUEUES
    assert REPORT_QUEUES.issubset({q.value for q in Queue})
    assert {t.value for t in ShareTarget} == SHARE_ENTITIES
    assert {d.value for d in AlertDelivery} == ALERT_DELIVERIES


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
            EventName.PHONE_VERIFIED,  # подтверждение телефона — v1
            user_id=new_id(),
            occurred_at=NOW,
            source_event_id=new_id(),
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

    assert list(fake.captured) == [event]
    assert logs == [
        {
            "event": "analytics_event",
            "log_level": "info",
            "name": "user_registered",
            "user_id": str(event.distinct_id),
            "properties": {"source": "legal", "entry_point": "bot", "has_referral": False},
        }
    ]


@pytest.mark.parametrize("status", [301, 308], ids=["moved", "permanent-redirect"])
async def test_posthog_redirect_is_not_delivery(status: int) -> None:
    """Редирект с неверного адреса (http://…) — не доставка: ошибка в лог, а не тишина."""
    analytics = posthog(lambda _: httpx.Response(status, headers={"Location": "https://x/"}))

    with capture_logs() as logs:
        await analytics.capture(registered(source="organic"))

    assert [(log["event"], log["status"]) for log in logs] == [("analytics_rejected", status)]


async def test_posthog_request_timeout_is_retried() -> None:
    with pytest.raises(ExternalServiceError):
        await posthog(lambda _: httpx.Response(408)).capture(registered(source="organic"))


def test_posthog_host_must_be_https() -> None:
    with pytest.raises(ValidationError, match="https"):
        AnalyticsSettings(posthog_host="http://eu.i.posthog.com")
    assert AnalyticsSettings(posthog_host="https://eu.i.posthog.com/").posthog_host == (
        "https://eu.i.posthog.com"
    )


@pytest.mark.parametrize(
    "event",
    [
        AnalyticsEvent(
            name="user_registered",
            distinct_id=new_id(),
            occurred_at=NOW,
            event_id=new_id(),
            properties={"phone": "+381641234567"},
        ),
        AnalyticsEvent(name="made_up", distinct_id=new_id(), occurred_at=NOW, event_id=new_id()),
        AnalyticsEvent(
            name="phone_verified", distinct_id=new_id(), occurred_at=NOW, event_id=new_id()
        ),
    ],
    ids=["pii-property", "unknown-event", "not-wired"],
)
async def test_adapters_refuse_events_built_around_the_taxonomy(event: AnalyticsEvent) -> None:
    """Проверка в адаптерах, а не только в analytics_event: событие, собранное напрямую, с
    телефоном в свойствах не уйдёт ни в PostHog, ни в лог."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    with pytest.raises(ValueError, match=r"taxonomy|wired|unknown property"):
        await posthog(handler).capture(event)
    with pytest.raises(ValueError, match=r"taxonomy|wired|unknown property"):
        await LoggingAnalytics().capture(event)
    assert sent == []


async def test_fake_keeps_only_the_latest_events() -> None:
    fake = LoggingAnalytics()
    for _ in range(fake.captured.maxlen + 5):  # type: ignore[operator]
        await fake.capture(registered(source="organic"))

    assert len(fake.captured) == fake.captured.maxlen


async def test_onboarding_and_write_access_handlers_send_their_events() -> None:
    fake = LoggingAnalytics()
    user_id = UserId(new_id())
    onboarded = OnboardingCompleted(
        user_id=user_id, intent="casual", home_city_id=CityId(7), occurred_at=NOW
    )
    no_profile = OnboardingCompleted(
        user_id=user_id, intent=None, home_city_id=None, occurred_at=NOW
    )
    granted = WriteAccessGranted(user_id=user_id, via="mini_app", occurred_at=NOW)
    waitlisted = GoodsWaitlistJoined(user_id=user_id, bot_writable=False, occurred_at=NOW)

    await capture_onboarding_completed(onboarded, fake)
    await capture_onboarding_completed(no_profile, fake)
    await capture_write_access_granted(granted, fake)
    await capture_goods_waitlist_joined(waitlisted, fake)

    assert [(e.name, dict(e.properties)) for e in fake.captured] == [
        ("onboarding_completed", {"intent": "casual", "city": 7}),
        ("onboarding_completed", {"intent": "unknown"}),
        ("write_access_granted", {"via": "mini_app"}),
        ("goods_waitlist_joined", {"bot_writable": False}),
    ]


async def test_deal_events_go_to_both_sides_once() -> None:
    """Сделка — по событию на каждую сторону: fill rate по клиентам, win rate по исполнителям.
    У копий разные id, а повтор задачи даёт те же — PostHog не удвоит."""
    fake = LoggingAnalytics()
    client, performer = UserId(new_id()), UserId(new_id())
    deal_id = DealId(new_id())
    agreed = DealAgreed(
        deal_id=deal_id,
        client_id=client,
        performer_id=performer,
        origin="job_response",
        job_id=new_id(),
        response_id=new_id(),
        category_id=CategoryId(5),
        occurred_at=NOW,
    )
    cancelled = DealCancelled(
        deal_id=deal_id,
        client_id=client,
        performer_id=performer,
        origin="chat",
        job_id=None,
        response_id=None,
        category_id=None,
        cancelled_by="performer",
        reason="no_contact",
        occurred_at=NOW,
    )

    await capture_deal_agreed(agreed, fake)
    await capture_deal_agreed(agreed, fake)  # повтор задачи
    await capture_deal_cancelled(cancelled, fake)

    events = list(fake.captured)
    assert [(e.name, e.distinct_id, dict(e.properties)) for e in events] == [
        ("deal_agreed", client, {"role": "client", "origin": "job_response", "category": 5}),
        ("deal_agreed", performer, {"role": "performer", "origin": "job_response", "category": 5}),
        ("deal_agreed", client, {"role": "client", "origin": "job_response", "category": 5}),
        ("deal_agreed", performer, {"role": "performer", "origin": "job_response", "category": 5}),
        (
            "deal_cancelled",
            client,
            {"role": "client", "origin": "chat", "by": "performer", "reason": "no_contact"},
        ),
        (
            "deal_cancelled",
            performer,
            {"role": "performer", "origin": "chat", "by": "performer", "reason": "no_contact"},
        ),
    ]
    assert events[0].event_id != events[1].event_id
    assert [events[0].event_id, events[1].event_id] == [events[2].event_id, events[3].event_id]


async def test_invites_and_direct_requests_are_captured() -> None:
    """5.6: приглашение и прямой запрос — без свойств, от клиента."""
    fake = LoggingAnalytics()
    client = UserId(new_id())

    for direct in (False, True):
        await capture_job_invited(
            JobInvited(
                job_id=new_id(),
                client_id=client,
                profile_id=new_id(),
                performer_id=UserId(new_id()),
                direct=direct,
                occurred_at=NOW,
            ),
            fake,
        )

    assert [(e.name, e.distinct_id) for e in fake.captured] == [
        ("invite_sent", client),
        ("direct_request_sent", client),
    ]


async def test_alert_events_carry_no_criteria_values() -> None:
    """5.7: подписка — какая зона и режим, без точки и районов; совпадения — одно событие на
    заявку от её автора: скольким подписчикам сразу и подборкой."""
    fake = LoggingAnalytics()
    performer, client = UserId(new_id()), UserId(new_id())
    await capture_alert_created(
        AlertCreated(
            alert_id=new_id(),
            user_id=performer,
            city_id=CityId(1),
            delivery="digest",
            area="radius",
            categories=2,
            has_budget=True,
            urgent_only=False,
            occurred_at=NOW,
        ),
        fake,
    )
    await capture_alerts_matched(
        AlertsMatched(
            job_id=new_id(),
            client_id=client,
            category_id=CategoryId(12),
            city_id=CityId(1),
            urgency="asap",
            instant=7,
            digest=3,
            occurred_at=NOW,
        ),
        fake,
    )

    created, matched = fake.captured
    assert (created.name, created.distinct_id) == ("alert_created", performer)
    assert created.properties == {
        "city": 1,
        "delivery": "digest",
        "area": "radius",
        "categories": 2,
        "has_budget": True,
        "urgent_only": False,
    }
    assert (matched.name, matched.distinct_id) == ("job_matched_notified", client)
    assert matched.properties == {
        "category": 12,
        "city": 1,
        "urgency": "asap",
        "instant": 7,
        "digest": 3,
    }


async def test_report_is_captured_from_the_reporter() -> None:
    """4.7: жалоба — от жалующегося, с типом объекта, причиной и очередью; без текста."""
    fake = LoggingAnalytics()
    reporter = UserId(new_id())
    await capture_report_created(
        ReportCreated(
            report_id=new_id(),
            reporter_id=reporter,
            target_type="profile",
            target_id=new_id(),
            reason="fraud",
            case_id=CaseId(new_id()),
            queue="fraud",
            occurred_at=NOW,
        ),
        fake,
    )

    [event] = fake.captured
    assert (event.name, event.distinct_id) == ("report_created", reporter)
    assert event.properties == {"target": "profile", "reason": "fraud", "queue": "fraud"}


async def test_share_and_attribution_feed_the_share_k_factor() -> None:
    """7.4: ссылка — от того, кто делится (на что и готова ли карточка); первое касание — от
    нового пользователя (тип ссылки и был ли код `_r`). Без id сущностей и кодов."""
    fake = LoggingAnalytics()
    sharer, newcomer = UserId(new_id()), UserId(new_id())
    await capture_share_created(
        ShareCreated(sharer_id=sharer, entity_type="job", prepared=True, occurred_at=NOW), fake
    )
    await capture_attribution_recorded(
        AttributionRecorded(
            user_id=newcomer, source="specialist", has_referral=True, occurred_at=NOW
        ),
        fake,
    )

    shared, attributed = fake.captured
    assert (shared.name, shared.distinct_id) == ("share_created", sharer)
    assert shared.properties == {"entity": "job", "prepared": True}
    assert (attributed.name, attributed.distinct_id) == ("attribution_recorded", newcomer)
    assert attributed.properties == {"source": "specialist", "has_referral": True}


async def test_chat_events_say_who_and_whether_contacts_were_hidden() -> None:
    """Диалог — кто начал и как; сообщение — чья сторона и скрыты ли контакты. Без текста."""
    fake = LoggingAnalytics()
    client, performer = UserId(new_id()), UserId(new_id())
    conversation_id = new_id()
    started = ConversationStarted(
        conversation_id=conversation_id,
        kind="job_response",
        initiator_id=performer,
        client_id=client,
        performer_id=performer,
        job_id=new_id(),
        response_id=new_id(),
        occurred_at=NOW,
    )
    sent = MessageSent(
        conversation_id=conversation_id,
        message_id=new_id(),
        sender_id=client,
        recipient_id=performer,
        sender_role="client",
        masked=True,
        occurred_at=NOW,
    )

    shared = ContactShared(
        conversation_id=conversation_id,
        deal_id=new_id(),
        shared_by=performer,
        shared_with=client,
        sharer_role="performer",
        contact_type="phone",
        occurred_at=NOW,
    )

    await capture_conversation_started(started, fake)
    await capture_message_sent(sent, fake)
    await capture_contact_shared(shared, fake)

    assert [(e.name, e.distinct_id, dict(e.properties)) for e in fake.captured] == [
        ("conversation_started", performer, {"kind": "job_response", "initiator": "performer"}),
        ("message_sent", client, {"role": "client", "masked": True}),
        ("contact_shared", performer, {"contact_type": "phone", "role": "performer"}),
    ]
