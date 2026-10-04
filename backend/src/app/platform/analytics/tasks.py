"""Задачи-подписчики аналитики (DEVELOPMENT_PLAN 1.7).

Доменное событие ставит задачу в той же транзакции, что и изменение (ADR-0020 §8): событие
аналитики уходит только после commit и не уходит при rollback. Здесь подключаются
`user_registered` (с источником атрибуции), `onboarding_completed` и `write_access_granted`
(1.7), `profile_submitted` и `profile_published` (2.8a), `job_published`, `job_closed` и
`job_expired` (5.1), `response_submitted` (5.4), `invite_sent` и `direct_request_sent` (5.6),
`deal_agreed`, `deal_completed` и `deal_cancelled` (6.1a) — по событию на каждую сторону сделки,
`dispute_opened` (6.1c) — открывшему, `conversation_started` и `message_sent` (6.3a),
`contact_shared` (6.3b), `review_published` (7.2), `report_created` (4.7), `alert_created` и
`job_matched_notified` (5.7), `share_created` и `attribution_recorded` (7.4),
`goods_waitlist_joined` (7.5), `pro_waitlist_joined` (2.7b, Q24); остальные события подключает
шаг своего модуля (таксономия — events.py).

`forget_person` — UserDeleted: персона удалённого аккаунта и её события удаляются в PostHog
(2.12b, posthog_persons.py); новые события о нём адаптер уже не отправляет (deleted.py).
`forget_person_again` — второй проход через сутки: событие, отправленное до удаления, PostHog
мог принять в обработку позже первого прохода (очередь приёма, задача capture на повторе в
момент commit удаления) — и завести персону заново. Первый проход — сразу, а не через час:
данные не лежат лишний час, неверный ключ виден в тот же день; позднее событие ловит второй.
"""

import uuid
from datetime import timedelta
from typing import Final
from uuid import UUID

from dishka import FromDishka

from app.platform.analytics.events import EventName, analytics_event
from app.platform.analytics.port import Analytics, AnalyticsEvent, PersonDeletion
from app.platform.contracts.events.deals import (
    DealAgreed,
    DealCancelled,
    DealCompleted,
    DealDisputed,
)
from app.platform.contracts.events.growth import AttributionRecorded, ShareCreated
from app.platform.contracts.events.identity import (
    OnboardingCompleted,
    UserDeleted,
    UserRegistered,
)
from app.platform.contracts.events.jobs import (
    AlertCreated,
    AlertsMatched,
    JobClosed,
    JobExpired,
    JobInvited,
    JobPublished,
    ResponseSubmitted,
)
from app.platform.contracts.events.messaging import ContactShared, ConversationStarted, MessageSent
from app.platform.contracts.events.moderation import ReportCreated
from app.platform.contracts.events.notifications import GoodsWaitlistJoined, WriteAccessGranted
from app.platform.contracts.events.reviews import ReviewPublished
from app.platform.contracts.events.specialists import (
    ProfilePublished,
    ProfileSubmitted,
    ProWaitlistJoined,
)
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import JitteredRetry, subscriber
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
CAPTURE_DISPUTE_OPENED = TaskRef("analytics.capture_dispute_opened", DealDisputed)
CAPTURE_CONVERSATION_STARTED = TaskRef(
    "analytics.capture_conversation_started", ConversationStarted
)
CAPTURE_MESSAGE_SENT = TaskRef("analytics.capture_message_sent", MessageSent)
CAPTURE_CONTACT_SHARED = TaskRef("analytics.capture_contact_shared", ContactShared)
CAPTURE_REVIEW_PUBLISHED = TaskRef("analytics.capture_review_published", ReviewPublished)
CAPTURE_REPORT_CREATED = TaskRef("analytics.capture_report_created", ReportCreated)
CAPTURE_SHARE_CREATED = TaskRef("analytics.capture_share_created", ShareCreated)
CAPTURE_ATTRIBUTION_RECORDED = TaskRef(
    "analytics.capture_attribution_recorded", AttributionRecorded
)
CAPTURE_ALERT_CREATED = TaskRef("analytics.capture_alert_created", AlertCreated)
CAPTURE_ALERTS_MATCHED = TaskRef("analytics.capture_alerts_matched", AlertsMatched)
CAPTURE_GOODS_WAITLIST_JOINED = TaskRef(
    "analytics.capture_goods_waitlist_joined", GoodsWaitlistJoined
)
CAPTURE_PRO_WAITLIST_JOINED = TaskRef("analytics.capture_pro_waitlist_joined", ProWaitlistJoined)
SECOND_PASS: Final = timedelta(hours=24)
FORGET_PERSON = TaskRef("analytics.forget_person", UserDeleted)
FORGET_PERSON_AGAIN = TaskRef("analytics.forget_person_again", UserDeleted, delay=SECOND_PASS)
FORGET_RETRY: Final = JitteredRetry(max_attempts=8, base_seconds=30.0, cap_seconds=3600.0)
"""Удаление не срочно по минутам: 7 повторов от 30 с до ~30 мин (около часа, с джиттером) —
время PostHog разобраться с `deletion_errors` и 5xx. Дальше задача в failed: ERROR-лог
Procrastinate — Sentry, перезапуск по runbook deletion-request.md."""


@subscriber(UserDeleted, FORGET_PERSON, retry=FORGET_RETRY)
async def forget_person(event: UserDeleted, persons: FromDishka[PersonDeletion]) -> None:
    """Аккаунт удалён (§7.10): персона и события в PostHog — по тому же distinct_id, что у
    capture (внутренний UUID). Временная ошибка PostHog — повтор задачи; повтор после успеха
    безопасен — персоны уже нет."""
    await persons.forget(event.user_id)


@subscriber(UserDeleted, FORGET_PERSON_AGAIN, retry=FORGET_RETRY)
async def forget_person_again(event: UserDeleted, persons: FromDishka[PersonDeletion]) -> None:
    """Второй проход через сутки (SECOND_PASS, docstring модуля): тот же идемпотентный запрос —
    персоны нет, `persons_found` 0; заведённую поздним событием удаляет с её событиями."""
    await persons.forget(event.user_id)


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
    rate (§16.2), город и категория заявки — разрез по паре, как у `job_published` (6.6). Без
    времени публикации (не должно случаться) — ноль минут; событие, поставленное до полей
    города и категории, уходит без них."""
    since = event.published_at or event.occurred_at
    minutes = max(0, int((event.occurred_at - since).total_seconds() // 60))
    pair: dict[str, int] = {}
    if event.category_id is not None:
        pair["category"] = event.category_id
    if event.city_id is not None:
        pair["city"] = event.city_id
    await analytics.capture(
        analytics_event(
            EventName.RESPONSE_SUBMITTED,
            user_id=event.performer_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            is_first=event.is_first,
            minutes_since_published=minutes,
            **pair,
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


@subscriber(DealDisputed, CAPTURE_DISPUTE_OPENED)
async def capture_dispute_opened(event: DealDisputed, analytics: FromDishka[Analytics]) -> None:
    """Спор — открывшему: доля сделок со спором и что чаще всего случается (6.1c)."""
    category = {"category": event.category_id} if event.category_id is not None else {}
    await analytics.capture(
        analytics_event(
            EventName.DISPUTE_OPENED,
            user_id=event.opened_by,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            role="client" if event.opened_by == event.client_id else "performer",
            kind=event.kind,
            origin=event.origin,
            **category,
        )
    )


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


@subscriber(ReviewPublished, CAPTURE_REVIEW_PUBLISHED)
async def capture_review_published(
    event: ReviewPublished, analytics: FromDishka[Analytics]
) -> None:
    """Review rate (6.6) — опубликованные отзывы к завершённым сделкам; от лица автора."""
    await analytics.capture(
        analytics_event(
            EventName.REVIEW_PUBLISHED,
            user_id=event.author_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            rating=event.rating,
            has_text=event.has_text,
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


@subscriber(ReportCreated, CAPTURE_REPORT_CREATED)
async def capture_report_created(event: ReportCreated, analytics: FromDishka[Analytics]) -> None:
    """Жалоба — от жалующегося: доля подтверждённых жалоб на сделки (метрика trust & safety)."""
    await analytics.capture(
        analytics_event(
            EventName.REPORT_CREATED,
            user_id=event.reporter_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            target=event.target_type,
            reason=event.reason,
            queue=event.queue,
        )
    )


@subscriber(ShareCreated, CAPTURE_SHARE_CREATED)
async def capture_share_created(event: ShareCreated, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.SHARE_CREATED,
            user_id=event.sharer_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            entity=event.entity_type,
            prepared=event.prepared,
        )
    )


@subscriber(AttributionRecorded, CAPTURE_ATTRIBUTION_RECORDED)
async def capture_attribution_recorded(
    event: AttributionRecorded, analytics: FromDishka[Analytics]
) -> None:
    await analytics.capture(
        analytics_event(
            EventName.ATTRIBUTION_RECORDED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            source=event.source,
            has_referral=event.has_referral,
        )
    )


@subscriber(AlertCreated, CAPTURE_ALERT_CREATED)
async def capture_alert_created(event: AlertCreated, analytics: FromDishka[Analytics]) -> None:
    await analytics.capture(
        analytics_event(
            EventName.ALERT_CREATED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            city=event.city_id,
            delivery=event.delivery,
            area=event.area,
            categories=event.categories,
            has_budget=event.has_budget,
            urgent_only=event.urgent_only,
        )
    )


@subscriber(AlertsMatched, CAPTURE_ALERTS_MATCHED)
async def capture_alerts_matched(event: AlertsMatched, analytics: FromDishka[Analytics]) -> None:
    """Сколько подписчиков узнали о заявке — от автора заявки (ликвидность по паре «город ×
    категория»); получатели в аналитику не уходят."""
    await analytics.capture(
        analytics_event(
            EventName.JOB_MATCHED_NOTIFIED,
            user_id=event.client_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            category=event.category_id,
            city=event.city_id,
            urgency=event.urgency,
            instant=event.instant,
            digest=event.digest,
        )
    )


@subscriber(GoodsWaitlistJoined, CAPTURE_GOODS_WAITLIST_JOINED)
async def capture_goods_waitlist_joined(
    event: GoodsWaitlistJoined, analytics: FromDishka[Analytics]
) -> None:
    """Лист ожидания «Вещей» (S58): сигнал спроса к точке решения 1 (ADR-0019)."""
    await analytics.capture(
        analytics_event(
            EventName.GOODS_WAITLIST_JOINED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
            bot_writable=event.bot_writable,
        )
    )


@subscriber(ProWaitlistJoined, CAPTURE_PRO_WAITLIST_JOINED)
async def capture_pro_waitlist_joined(
    event: ProWaitlistJoined, analytics: FromDishka[Analytics]
) -> None:
    """Лист ожидания Pro (Q24): «Хочу узнать первым» в рассылке founding-специалистам (2.7b)."""
    await analytics.capture(
        analytics_event(
            EventName.PRO_WAITLIST_JOINED,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            source_event_id=event.event_id,
        )
    )
