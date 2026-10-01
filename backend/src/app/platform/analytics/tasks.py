"""Задачи-подписчики аналитики (DEVELOPMENT_PLAN 1.7).

Доменное событие ставит задачу в той же транзакции, что и изменение (ADR-0020 §8): событие
аналитики уходит только после commit и не уходит при rollback. Здесь подключаются
`user_registered` (с источником атрибуции), `onboarding_completed` и `write_access_granted`
(1.7), `profile_submitted` и `profile_published` (2.8a); остальные события подключает шаг
своего модуля (таксономия — events.py).
"""

from dishka import FromDishka

from app.platform.analytics.events import EventName, analytics_event
from app.platform.analytics.port import Analytics
from app.platform.contracts.events.identity import OnboardingCompleted, UserRegistered
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
