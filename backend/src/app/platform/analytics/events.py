"""Таксономия событий аналитики (DEVELOPMENT_PLAN 1.7): имя, свойства и метрики PRODUCT.

Правило DoD: шаг, в котором появляется факт, подключает его событие — задаёт свойства и
задачу-подписчик. Пока у события нет свойств (`properties is None`), оно только объявлено:
`analytics_event` его не соберёт, и событие без схемы не уйдёт.

Свойства — без персональных данных: Choice — значение из закрытого списка, Flag, Count
(целое ≥ 0), Ref — id справочника (город, категория). Свободного текста нет: имя, телефон,
@username или текст сообщения свойством стать не могут.

METRICS — все метрики раздела «Метрики успеха» PRODUCT: из каких событий (или запросов)
каждая считается и с какого шага. Тест сверяет список с PRODUCT.md.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.platform.analytics.port import AnalyticsEvent, PropertyValue
from app.platform.telegram.deeplinks import LinkSource


class EventName(StrEnum):
    USER_REGISTERED = "user_registered"
    ONBOARDING_COMPLETED = "onboarding_completed"
    WRITE_ACCESS_GRANTED = "write_access_granted"
    PROFILE_SUBMITTED = "profile_submitted"
    PROFILE_PUBLISHED = "profile_published"
    PRO_WAITLIST_JOINED = "pro_waitlist_joined"
    PHONE_VERIFIED = "phone_verified"
    REPORT_CREATED = "report_created"
    JOB_PUBLISHED = "job_published"
    JOB_CLOSED = "job_closed"
    JOB_EXPIRED = "job_expired"
    RESPONSE_SUBMITTED = "response_submitted"
    INVITE_SENT = "invite_sent"
    DIRECT_REQUEST_SENT = "direct_request_sent"
    ALERT_CREATED = "alert_created"
    JOB_MATCHED_NOTIFIED = "job_matched_notified"
    DEAL_AGREED = "deal_agreed"
    DEAL_COMPLETED = "deal_completed"
    DEAL_CANCELLED = "deal_cancelled"
    DISPUTE_OPENED = "dispute_opened"
    CONVERSATION_STARTED = "conversation_started"
    MESSAGE_SENT = "message_sent"
    CONTACT_SHARED = "contact_shared"
    REVIEW_PUBLISHED = "review_published"
    SHARE_CREATED = "share_created"
    ATTRIBUTION_RECORDED = "attribution_recorded"
    GOODS_WAITLIST_JOINED = "goods_waitlist_joined"


@dataclass(frozen=True, slots=True)
class Choice:
    """Строка из закрытого списка."""

    values: frozenset[str]

    def check(self, value: PropertyValue) -> bool:
        return isinstance(value, str) and value in self.values


@dataclass(frozen=True, slots=True)
class Flag:
    def check(self, value: PropertyValue) -> bool:
        return isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class Count:
    """Целое ≥ 0: число откликов, фото, минуты до ответа."""

    def check(self, value: PropertyValue) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True, slots=True)
class Ref:
    """Id справочника (город, район, категория) — не id пользователя или объекта."""

    def check(self, value: PropertyValue) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0


type Property = Choice | Flag | Count | Ref

INTENTS: Final = frozenset({"client", "pro", "casual", "unknown"})
"""UserIntent identity (S02b) и `unknown`, если шаг пропустили."""
ENTRY_POINTS: Final = frozenset({"mini_app", "bot", "unknown"})
"""EntryPoint из UserRegistered; `unknown` — у событий, поставленных до 1.4b."""
WRITE_ACCESS_VIA: Final = frozenset({"bot_start", "mini_app"})
PROFILE_KINDS: Final = frozenset({"pro", "casual"})
"""GrantedVia notifications: /start в боте или requestWriteAccess в Mini App."""
URGENCIES: Final = frozenset({"asap", "today", "this_week", "flexible"})
"""Urgency заявки (jobs); сверяет тест модуля jobs."""
CLOSE_REASONS: Final = frozenset(
    {"hired_here", "hired_elsewhere", "not_needed", "no_suitable", "expired", "removed"}
)
"""CloseReason заявки (jobs): причины клиента, срок и снятие модерацией."""
DEAL_ROLES: Final = frozenset({"client", "performer"})
"""Чья копия события сделки: метрики клиента (fill rate) и исполнителя (win rate, концентрация)
считаются по своей стороне."""
DEAL_ORIGINS: Final = frozenset({"job_response", "direct", "chat"})
"""DealOrigin сделки (deals)."""
DEAL_CANCELLED_BY: Final = frozenset({"client", "performer", "system", "moderator"})
DEAL_CANCEL_REASONS: Final = frozenset(
    {
        "plans_changed",
        "no_agreement",
        "no_contact",
        "other",
        "expired",
        "account_deleted",
        "dispute",
    }
)
"""DealCancelReason сделки (deals): причины стороны, системы и модератора по спору (6.1c)."""
DISPUTE_KINDS: Final = frozenset(
    {"no_show", "quality", "prepayment_taken", "damage", "safety", "other"}
)
"""DisputeKind спора (deals, 6.1c): что случилось."""
CONVERSATION_KINDS: Final = frozenset({"job_response", "direct"})
"""ConversationKind диалога (messaging), который начинают пользователи."""
CONTACT_TYPES: Final = frozenset({"telegram", "phone"})
"""ContactType (messaging): чем поделились после договорённости."""
REPORT_TARGETS: Final = frozenset({"profile", "job", "review", "message", "user"})
"""На что жалуются (moderation, 4.7): типы объектов шторки S46."""
REPORT_REASONS: Final = frozenset(
    {
        "spam",
        "fraud",
        "prohibited",
        "offensive",
        "fake_profile",
        "no_show",
        "personal_data",
        "defamation",
        "copyright",
        "illegal",
        "other",
    }
)
"""ReportReason жалобы (moderation, 4.7)."""
REPORT_QUEUES: Final = frozenset({"safety", "fraud"})
"""Очередь кейса жалобы: P0 или P1 (§14.2)."""
SHARE_ENTITIES: Final = frozenset({"specialist", "job"})
"""ShareTarget growth (7.4): чем делятся — карточкой специалиста или заявкой."""
ALERT_DELIVERIES: Final = frozenset({"instant", "digest"})
"""AlertDelivery подписки (jobs, 5.7): сразу или подборкой."""
ALERT_AREAS: Final = frozenset({"city", "districts", "radius"})
"""Зона подписки: весь город, районы или радиус от точки."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EventSpec:
    step: str
    """Шаг плана, который подключает событие (задаёт свойства и подписчика)."""
    description: str
    properties: Mapping[str, Property] | None = None
    """None — событие объявлено, но ещё не подключено."""


EVENTS: Final[Mapping[EventName, EventSpec]] = {
    EventName.USER_REGISTERED: EventSpec(
        step="1.7",
        description="Новый аккаунт: первый вход в Mini App или /start в боте",
        properties={
            "source": Choice(frozenset(s.value for s in LinkSource)),
            "entry_point": Choice(ENTRY_POINTS),
            "has_referral": Flag(),
        },
    ),
    EventName.ONBOARDING_COMPLETED: EventSpec(
        step="1.7",
        description="Первое согласие с правилами на S02c — онбординг пройден",
        properties={"intent": Choice(INTENTS), "city": Ref()},
    ),
    EventName.WRITE_ACCESS_GRANTED: EventSpec(
        step="1.7",
        description="Боту можно писать: канал telegram появился или включился снова",
        properties={"via": Choice(WRITE_ACCESS_VIA)},
    ),
    EventName.PROFILE_SUBMITTED: EventSpec(
        step="2.8a",
        description="Профиль исполнителя отправлен на проверку (S32c или переход в «Специалист»)",
        properties={"kind": Choice(PROFILE_KINDS)},
    ),
    EventName.PROFILE_PUBLISHED: EventSpec(
        step="2.8a",
        description="Профиль в каталоге: одобрен модерацией или возвращён владельцем",
        properties={"approved": Flag()},
    ),
    EventName.PRO_WAITLIST_JOINED: EventSpec(step="2.8a", description="Лист ожидания Pro"),
    EventName.PHONE_VERIFIED: EventSpec(step="2.9", description="Телефон подтверждён"),
    EventName.REPORT_CREATED: EventSpec(
        step="4.7",
        description="Жалоба (S46): на что, причина и очередь кейса — от жалующегося",
        properties={
            "target": Choice(REPORT_TARGETS),
            "reason": Choice(REPORT_REASONS),
            "queue": Choice(REPORT_QUEUES),
        },
    ),
    EventName.JOB_PUBLISHED: EventSpec(
        step="5.1",
        description="Заявка опубликована: после проверки или снова — продлением истёкшей",
        properties={
            "category": Ref(),
            "city": Ref(),
            "urgency": Choice(URGENCIES),
            "republished": Flag(),
        },
    ),
    EventName.JOB_CLOSED: EventSpec(
        step="5.1",
        description="Заявка закрыта клиентом (с причиной), удалена или снята модерацией",
        properties={"category": Ref(), "city": Ref(), "reason": Choice(CLOSE_REASONS)},
    ),
    EventName.JOB_EXPIRED: EventSpec(
        step="5.1",
        description="Срок заявки вышел",
        properties={"category": Ref(), "city": Ref()},
    ),
    EventName.RESPONSE_SUBMITTED: EventSpec(
        step="5.4",
        description="Отклик на заявку: первый ли и через сколько минут после публикации (TTFR)",
        properties={"is_first": Flag(), "minutes_since_published": Count()},
    ),
    EventName.INVITE_SENT: EventSpec(step="5.6", description="Приглашение в заявку", properties={}),
    EventName.DIRECT_REQUEST_SENT: EventSpec(
        step="5.6",
        description="Прямой запрос: опубликован, и специалист о нём узнал",
        properties={},
    ),
    EventName.ALERT_CREATED: EventSpec(
        step="5.7",
        description="Подписка на заявки (S19): как присылать, какая зона, сколько категорий",
        properties={
            "city": Ref(),
            "delivery": Choice(ALERT_DELIVERIES),
            "area": Choice(ALERT_AREAS),
            "categories": Count(),
            "has_budget": Flag(),
            "urgent_only": Flag(),
        },
    ),
    EventName.JOB_MATCHED_NOTIFIED: EventSpec(
        step="5.7",
        description="Заявка подошла подписчикам: скольким — карточкой B1 сразу и подборкой — "
        "одно событие на заявку от её автора",
        properties={
            "category": Ref(),
            "city": Ref(),
            "urgency": Choice(URGENCIES),
            "instant": Count(),
            "digest": Count(),
        },
    ),
    EventName.DEAL_AGREED: EventSpec(
        step="6.1a",
        description="Стороны договорились: выбран отклик или подтверждено «Договорились» — по "
        "событию на каждую сторону (`role`)",
        properties={"role": Choice(DEAL_ROLES), "origin": Choice(DEAL_ORIGINS), "category": Ref()},
    ),
    EventName.DEAL_COMPLETED: EventSpec(
        step="6.1a",
        description="Сделка завершена — по событию на каждую сторону",
        properties={"role": Choice(DEAL_ROLES), "origin": Choice(DEAL_ORIGINS), "category": Ref()},
    ),
    EventName.DEAL_CANCELLED: EventSpec(
        step="6.1a",
        description="Сделка отменена: кем и почему — по событию на каждую сторону",
        properties={
            "role": Choice(DEAL_ROLES),
            "origin": Choice(DEAL_ORIGINS),
            "category": Ref(),
            "by": Choice(DEAL_CANCELLED_BY),
            "reason": Choice(DEAL_CANCEL_REASONS),
        },
    ),
    EventName.DISPUTE_OPENED: EventSpec(
        step="6.1c",
        description="Открыт спор по сделке: кто открыл (`role`) и что случилось (`kind`)",
        properties={
            "role": Choice(DEAL_ROLES),
            "kind": Choice(DISPUTE_KINDS),
            "origin": Choice(DEAL_ORIGINS),
            "category": Ref(),
        },
    ),
    EventName.CONVERSATION_STARTED: EventSpec(
        step="6.3a",
        description="Начат диалог: по отклику или прямым обращением, кто начал (`initiator`)",
        properties={"kind": Choice(CONVERSATION_KINDS), "initiator": Choice(DEAL_ROLES)},
    ),
    EventName.MESSAGE_SENT: EventSpec(
        step="6.3a",
        description="Сообщение в чате: чья сторона и скрыты ли контакты до договорённости",
        properties={"role": Choice(DEAL_ROLES), "masked": Flag()},
    ),
    EventName.CONTACT_SHARED: EventSpec(
        step="6.3b",
        description="Сторона поделилась контактом после договорённости: чем и чья сторона",
        properties={"contact_type": Choice(CONTACT_TYPES), "role": Choice(DEAL_ROLES)},
    ),
    EventName.REVIEW_PUBLISHED: EventSpec(
        step="7.2",
        description="Опубликован отзыв по сделке (прошёл проверку): оценка и есть ли текст",
        properties={"rating": Count(), "has_text": Flag()},
    ),
    EventName.SHARE_CREATED: EventSpec(
        step="7.4",
        description="«Поделиться»: вошедший взял ссылку со своим кодом `_r` — на что и готова ли "
        "карточка для shareMessage",
        properties={"entity": Choice(SHARE_ENTITIES), "prepared": Flag()},
    ),
    EventName.ATTRIBUTION_RECORDED: EventSpec(
        step="7.4",
        description="Первое касание нового пользователя: тип ссылки и был ли код `_r`",
        properties={
            "source": Choice(frozenset(s.value for s in LinkSource)),
            "has_referral": Flag(),
        },
    ),
    EventName.GOODS_WAITLIST_JOINED: EventSpec(
        step="7.5",
        description="«Сообщить о запуске» на S58: может ли бот написать сейчас",
        properties={"bot_writable": Flag()},
    ),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricSpec:
    name: str
    """Как в первой колонке таблиц «Метрики успеха» PRODUCT."""
    step: str
    """С какого шага метрика считается (или `v1` — после MVP)."""
    events: tuple[EventName, ...] = ()
    source: str = "события"
    """Откуда считается, если не только из событий: SQL по таблице, выборочный аудит."""


NORTH_STAR: Final = MetricSpec(
    name="deals.completed",
    step="6.1a",
    events=(EventName.DEAL_COMPLETED,),
)
"""North Star: сделки, завершённые через платформу за неделю, по паре «город × категория»."""

_E = EventName
METRICS: Final[tuple[MetricSpec, ...]] = (
    # Ликвидность
    MetricSpec(
        name="Response rate@1h", step="5.4", events=(_E.JOB_PUBLISHED, _E.RESPONSE_SUBMITTED)
    ),
    MetricSpec(
        name="Response rate@4h", step="5.4", events=(_E.JOB_PUBLISHED, _E.RESPONSE_SUBMITTED)
    ),
    MetricSpec(
        name="Response rate@24h", step="5.4", events=(_E.JOB_PUBLISHED, _E.RESPONSE_SUBMITTED)
    ),
    MetricSpec(name="Глубина", step="5.4", events=(_E.RESPONSE_SUBMITTED,)),
    MetricSpec(name="TTFR", step="5.4", events=(_E.JOB_PUBLISHED, _E.RESPONSE_SUBMITTED)),
    MetricSpec(name="Fill rate@7d", step="6.1a", events=(_E.JOB_PUBLISHED, _E.DEAL_AGREED)),
    MetricSpec(name="Completion rate", step="6.1a", events=(_E.DEAL_AGREED, _E.DEAL_COMPLETED)),
    MetricSpec(
        name="Win rate отклика", step="6.1a", events=(_E.RESPONSE_SUBMITTED, _E.DEAL_AGREED)
    ),
    MetricSpec(name="Supply/demand", step="5.4", events=(_E.JOB_PUBLISHED, _E.RESPONSE_SUBMITTED)),
    # Стороны и удержание
    MetricSpec(name="Weekly active specialists", step="5.4", events=(_E.RESPONSE_SUBMITTED,)),
    MetricSpec(
        name="Доля активных среди профилей",
        step="5.4",
        events=(_E.PROFILE_PUBLISHED, _E.RESPONSE_SUBMITTED),
    ),
    MetricSpec(
        name="Opt-in уведомлений",
        step="1.7",
        events=(_E.USER_REGISTERED, _E.WRITE_ACCESS_GRANTED),
        # доля с доступным каналом — состояние: заблокировавший бота (403, шаг 2.3b) выпадает
        source="SQL по notifications.channels (disabled_at IS NULL); события — динамика",
    ),
    MetricSpec(
        name="Repeat rate клиентов",
        step="5.6",
        events=(_E.JOB_PUBLISHED, _E.DIRECT_REQUEST_SENT),
    ),
    MetricSpec(name="6-месячное удержание", step="6.1a", events=(_E.DEAL_COMPLETED,)),
    MetricSpec(
        name="K-фактор шаринга",
        step="7.4",
        events=(_E.SHARE_CREATED, _E.ATTRIBUTION_RECORDED, _E.USER_REGISTERED),
    ),
    # Доверие и качество
    MetricSpec(name="Review rate", step="7.2", events=(_E.DEAL_COMPLETED, _E.REVIEW_PUBLISHED)),
    MetricSpec(
        name="Жалобы на мошенничество",
        step="6.1a",
        events=(_E.REPORT_CREATED, _E.DEAL_COMPLETED),
    ),
    MetricSpec(name="SLA модерации", step="2.5a", source="SQL по moderation.cases"),
    MetricSpec(
        name="Точность автомодерации",
        step="2.6",
        source="выборочный аудит решений автомодерации",
    ),
    MetricSpec(name="Доля KYC", step="v1", source="KYC появляется в v1"),
    MetricSpec(name="Концентрация", step="6.1a", events=(_E.DEAL_AGREED,)),
    # Бизнес (с v1)
    MetricSpec(name="GMV proxy", step="v1", events=(_E.DEAL_COMPLETED,)),
    MetricSpec(name="Конверсия в Pro", step="v1", source="billing (v1)"),
    MetricSpec(name="ARPPU, LTV:CAC", step="v1", source="billing (v1)"),
)

_EVENT_ID_NAMESPACE: Final = UUID("5b1d5b7e-8f5a-4a57-9a0e-2f1c6b0d7e11")


def ensure_allowed(event: AnalyticsEvent) -> None:
    """Событие соответствует таксономии: подключено, свойства из схемы. Адаптеры проверяют
    каждое событие перед отправкой — даже собранное в обход analytics_event."""
    try:
        name = EventName(event.name)
    except ValueError:
        raise ValueError(f"{event.name}: event is not in the taxonomy") from None
    _check_properties(name, event.properties)


def _check_properties(name: EventName, properties: Mapping[str, PropertyValue]) -> None:
    spec = EVENTS[name]
    if spec.properties is None:
        raise ValueError(f"{name}: event is declared but not wired yet (step {spec.step})")
    for key, value in properties.items():
        kind = spec.properties.get(key)
        if kind is None:
            raise ValueError(f"{name}: unknown property {key!r}")
        if not kind.check(value):
            raise ValueError(f"{name}.{key}: value is not allowed by the taxonomy")


def analytics_event(
    name: EventName,
    *,
    user_id: UUID,
    occurred_at: datetime,
    source_event_id: UUID,
    **properties: PropertyValue,
) -> AnalyticsEvent:
    """Событие по таксономии. Неизвестное свойство или значение вне схемы — ValueError:
    это ошибка программиста, а не данных, и она не должна уйти в аналитику молча."""
    _check_properties(name, properties)
    return AnalyticsEvent(
        name=name.value,
        distinct_id=user_id,
        occurred_at=occurred_at,
        # то же доменное событие → тот же id: повтор задачи не удваивает событие
        event_id=uuid.uuid5(_EVENT_ID_NAMESPACE, f"{source_event_id}:{name.value}"),
        properties=dict(properties),
    )
