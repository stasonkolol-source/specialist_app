"""Задачи-подписчики аналитики (DEVELOPMENT_PLAN 1.7).

Доменное событие ставит задачу в той же транзакции, что и изменение (ADR-0020 §8): событие
аналитики уходит только после commit и не уходит при rollback. Здесь подключаются
`user_registered` (с источником атрибуции), `onboarding_completed` и `write_access_granted`
(1.7), `profile_submitted` и `profile_published` (2.8a), `job_published`, `job_closed` и
`job_expired` (5.1), `response_submitted` (5.4), `invite_sent` и `direct_request_sent` (5.6),
`deal_agreed`, `deal_completed` и `deal_cancelled` (6.1a) — по событию на каждую сторону сделки,
`conversation_started` и `message_sent` (6.3a), `contact_shared` (6.3b); остальные события
подключает шаг своего модуля (таксономия — events.py).
"""

import uuid
from uuid import UUID

from dishka import FromDishka

from app.platform.analytics.events import EventName, analytics_event
from app.platform.analytics.port import Analytics, AnalyticsEvent
from app.platform.contracts.events.deals import DealAgreed, DealCancelled, DealCompleted
from app.platform.contracts.events.identity import OnboardingCompleted, UserRegistered
from app.platform.contracts.events.jobs import (
    JobClosed,
    JobExpired,
    JobInvited,
    JobPublished,
    ResponseSubmitted,
)
from app.platform.contracts.events.messaging import ContactShared, ConversationStarted, MessageSent
from app.platform.contracts.events.notifications import WriteAccessGranted
from app.platform.contracts.events.specialists import ProfilePublished, ProfileSubmitted
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import subscriber
from app.platform.telegram.deeplinks import link_source, parse_start_param

CAPTURE_USER_REGISTERED = TaskRef("analytics.capture_user_registered", UserRegistered)
CAPTURE_ONBOARDING_COMPLETED = TaskRef(
    "analytics.capture_onboarding_completed", OnboardingCompleted
)
CAPTURE_WRITE_ACCESS_GRANTED = TaskRef("analytics.capture_write_access_granted", WriteAccessGranted)
CAPTURE_PROFILE_SUBMITTED = TaskRef("analytics.capture_profile_submitted", ProfileSubmitted)
CAPTURE_PROFILE_PUBLISHED = TaskRef("analytics.capture_profile_published", ProfilePublished)
CAPTURE_JOB_PUBLISHED = TaskRef("analytics.capture_job_published", JobPublished)
CAPTURE_JOB_CLOSED = TaskRef("analytics.capture_job_closed", JobClosed)
CAPTURE_JOB_EXPIRED = TaskRef("analytics.capture_job_expired", JobExpired)
CAPTURE_RESPONSE_SUBMITTED = TaskRef("analytics.capture_response_submitted", ResponseSubmitted)
CAPTURE_JOB_INVITED = TaskRef("analytics.capture_job_invited", JobInvited)
CAPTURE_DEAL_AGREED = TaskRef("analytics.capture_deal_agreed", DealAgreed)
CAPTURE_DEAL_COMPLETED = TaskRef("analytics.capture_deal_completed", DealCompleted)
CAPTURE_DEAL_CANCELLED = TaskRef("analytics.capture_deal_cancelled", DealCancelled)
CAPTURE_CONVERSATION_STARTED = TaskRef(
    "analytics.capture_conversation_started", ConversationStarted
)
CAPTURE_MESSAGE_SENT = TaskRef("analytics.capture_message_sent", MessageSent)
CAPTURE_CONTACT_SHARED = TaskRef("analytics.capture_contact_shared", ContactShared)


@subscriber(UserRegistered, CAPTURE_USER_REGISTERED)
async def capture_user_registered(event: UserRegistered, analytics: FromDishka[Analytics]) -> None:
    link = parse_start_param(event.start_param)
    await analytics.capture(
        analytics_event(
            EventName.USER_REGISTERED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            source=link_source(event.start_param).value,
            entry_point=event.entry_point.value if event.entry_point else "unknown",
            has_referral=link is not None and link.ref is not None,
        )
    )


@subscriber(OnboardingCompleted, CAPTURE_ONBOARDING_COMPLETED)
async def capture_onboarding_completed(
    event: OnboardingCompleted, analytics: FromDishka[Analytics]
) -> None:
    city = {"city": event.home_city_id} if event.home_city_id is not None else {}
    await analytics.capture(
        analytics_event(
            EventName.ONBOARDING_COMPLETED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            intent=event.intent or "unknown",
            **city,
        )
    )


@subscriber(WriteAccessGranted, CAPTURE_WRITE_ACCESS_GRANTED)
async def capture_write_access_granted(
    event: WriteAccessGranted, analytics: FromDishka[Analytics]
) -> None:
    await analytics.capture(
        analytics_event(
            EventName.WRITE_ACCESS_GRANTED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            via=event.via,
        )
    )


@subscriber(ProfileSubmitted, CAPTURE_PROFILE_SUBMITTED)
async def capture_profile_submitted(
    event: ProfileSubmitted, analytics: FromDishka[Analytics]
) -> None:
    await analytics.capture(
        analytics_event(
            EventName.PROFILE_SUBMITTED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            kind=event.kind,
        )
    )


@subscriber(ProfilePublished, CAPTURE_PROFILE_PUBLISHED)
async def capture_profile_published(
    event: ProfilePublished, analytics: FromDishka[Analytics]
) -> None:
    await analytics.capture(
        analytics_event(
            EventName.PROFILE_PUBLISHED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            approved=event.approved,
        )
    )


@subscriber(JobPublished, CAPTURE_JOB_PUBLISHED)
async def capture_job_published(event: JobPublished, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.JOB_PUBLISHED,
            user_id=event.client_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            category=event.category_id,
            city=event.city_id,
            urgency=event.urgency,
            republished=event.republished,
        )
    )


@subscriber(JobClosed, CAPTURE_JOB_CLOSED)
async def capture_job_closed(event: JobClosed, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.JOB_CLOSED,
            user_id=event.client_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            category=event.category_id,
            city=event.city_id,
            reason=event.reason,
        )
    )


@subscriber(JobExpired, CAPTURE_JOB_EXPIRED)
async def capture_job_expired(event: JobExpired, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.JOB_EXPIRED,
            user_id=event.client_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            category=event.category_id,
            city=event.city_id,
        )
    )


@subscriber(ResponseSubmitted, CAPTURE_RESPONSE_SUBMITTED)
async def capture_response_submitted(
    event: ResponseSubmitted, analytics: FromDishka[Analytics]
) -> None:
    """Отклик: первый ли на заявку и через сколько минут после публикации — TTFR и response
    rate (§16.2). Без времени публикации (не должно случаться) — ноль минут."""
    since = event.published_at or event.occurred_at
    minutes = max(0, int((event.occurred_at - since).total_seconds() // 60))
    await analytics.capture(
        analytics_event(
            EventName.RESPONSE_SUBMITTED,
            user_id=event.performer_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            is_first=event.is_first,
            minutes_since_published=minutes,
        )
    )


@subscriber(JobInvited, CAPTURE_JOB_INVITED)
async def capture_job_invited(event: JobInvited, analytics: FromDishka[Analytics]) -> None:
    """Клиент позвал специалиста: приглашение в заявку или прямой запрос (5.6). Прямой запрос
    считается, когда его опубликовали и специалист о нём узнал."""
    await analytics.capture(
        analytics_event(
            EventName.DIRECT_REQUEST_SENT if event.direct else EventName.INVITE_SENT,
            user_id=event.client_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
        )
    )


@subscriber(DealAgreed, CAPTURE_DEAL_AGREED)
async def capture_deal_agreed(event: DealAgreed, analytics: FromDishka[Analytics]) -> None:
    for captured in _deal_sides(EventName.DEAL_AGREED, event):
        await analytics.capture(captured)


@subscriber(DealCompleted, CAPTURE_DEAL_COMPLETED)
async def capture_deal_completed(event: DealCompleted, analytics: FromDishka[Analytics]) -> None:
    for captured in _deal_sides(EventName.DEAL_COMPLETED, event):
        await analytics.capture(captured)


@subscriber(DealCancelled, CAPTURE_DEAL_CANCELLED)
async def capture_deal_cancelled(event: DealCancelled, analytics: FromDishka[Analytics]) -> None:
    for captured in _deal_sides(
        EventName.DEAL_CANCELLED, event, by=event.cancelled_by, reason=event.reason
    ):
        await analytics.capture(captured)


@subscriber(ConversationStarted, CAPTURE_CONVERSATION_STARTED)
async def capture_conversation_started(
    event: ConversationStarted, analytics: FromDishka[Analytics]
) -> None:
    initiator = "client" if event.initiator_id == event.client_id else "performer"
    await analytics.capture(
        analytics_event(
            EventName.CONVERSATION_STARTED,
            user_id=event.initiator_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            kind=event.kind,
            initiator=initiator,
        )
    )


@subscriber(MessageSent, CAPTURE_MESSAGE_SENT)
async def capture_message_sent(event: MessageSent, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.MESSAGE_SENT,
            user_id=event.sender_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            role=event.sender_role,
            masked=event.masked,
        )
    )


@subscriber(ContactShared, CAPTURE_CONTACT_SHARED)
async def capture_contact_shared(event: ContactShared, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.CONTACT_SHARED,
            user_id=event.shared_by,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            contact_type=event.contact_type,
            role=event.sharer_role,
        )
    )


def _deal_sides(
    name: EventName,
    event: DealAgreed | DealCompleted | DealCancelled,
    **extra: str,
) -> list[AnalyticsEvent]:
    """По событию на каждую сторону сделки: fill rate считается по клиентам, win rate и
    концентрация — по исполнителям. У копий свои id: повтор задачи не удваивает ни одну."""
    sides = (("client", event.client_id), ("performer", event.performer_id))
    category = {"category": event.category_id} if event.category_id is not None else {}
    return [
        analytics_event(
            name,
            user_id=user_id,
            occurred_at=event.occurred_at,
            source_event_id=_side_id(event.event_id, role),
            role=role,
            origin=event.origin,
            **category,
            **extra,
        )
        for role, user_id in sides
    ]


def _side_id(event_id: UUID, role: str) -> UUID:
    return uuid.uuid5(event_id, role)
