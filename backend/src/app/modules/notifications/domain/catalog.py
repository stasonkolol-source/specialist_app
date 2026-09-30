"""Каталог уведомлений MVP (ARCHITECTURE §11.2, §11.3): группа, приоритет, каналы, тихие часы.

Группа — строка настроек S43 («группы × каналы»); служебная группа `account` (решения
модерации, санкции) не выключается: без неё человек не узнает, почему контент не виден или
действие запрещено. Тексты — шаблоны gettext `notifications.<тип>.*` (rendering.py); тип
получает шаблоны вместе с подписчиком, который его создаёт: в 2.3a это `moderation.decision`
и `account.restricted`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType


class NotificationType(StrEnum):
    JOB_MATCHED = "job.matched"
    RESPONSE_RECEIVED = "response.received"
    RESPONSE_ACCEPTED = "response.accepted"
    RESPONSE_NOT_SELECTED = "response.not_selected"
    JOB_INVITED = "job.invited"
    MESSAGE_RECEIVED = "message.received"
    DEAL_PROPOSED = "deal.proposed"
    DEAL_CANCELLED = "deal.cancelled"
    DISPUTE_OPENED = "dispute.opened"
    DEAL_REMINDER = "deal.reminder"
    DEAL_COMPLETION_PROMPT = "deal.completion_prompt"
    REVIEW_REQUEST = "review.request"
    REVIEW_PUBLISHED = "review.published"
    MODERATION_DECISION = "moderation.decision"
    JOB_EXPIRING = "job.expiring"
    JOB_EXPIRED = "job.expired"
    PROFILE_STALE_REMINDER = "profile.stale_reminder"
    ACCOUNT_RESTRICTED = "account.restricted"


class EventGroup(StrEnum):
    """Строка настроек уведомлений S43."""

    JOB_MATCHES = "job_matches"
    """«Заявки по подпискам»: подходящие заявки и напоминания исполнителю."""
    RESPONSES = "responses"
    """«Отклики и выбор»: отклики, приглашения, выбор исполнителя, срок заявки."""
    MESSAGES = "messages"
    DEALS = "deals"
    """«Сделки, споры, отзывы»."""
    MARKETING = "marketing"
    """«Новости «Соседей»»: только по согласию (opt-in)."""
    ACCOUNT = "account"
    """Служебные: решения модерации и санкции. Не выключаются."""


MANDATORY_GROUPS = frozenset({EventGroup.ACCOUNT})
OPT_IN_GROUPS = frozenset({EventGroup.MARKETING})
"""Выключены, пока человек сам не включит."""


class Priority(IntEnum):
    """При перегрузке отправителя первыми уходят меньшие (§11.2)."""

    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class Channel(StrEnum):
    """Канал в настройках: личный чат с ботом и центр уведомлений в Mini App (S42)."""

    TELEGRAM = "telegram"
    IN_APP = "in_app"


BOT = frozenset({Channel.TELEGRAM})
BOT_AND_APP = frozenset({Channel.TELEGRAM, Channel.IN_APP})


@dataclass(frozen=True, slots=True, kw_only=True)
class TypeSpec:
    group: EventGroup
    priority: Priority
    channels: frozenset[Channel]
    quiet_exempt: bool = False
    """Уходит и в тихие часы: сообщения, выбор исполнителя, `deal.proposed` (§11.2). Заявки
    `asap` — по флагу срочности у конкретного уведомления."""


CATALOG: Mapping[NotificationType, TypeSpec] = MappingProxyType(
    {
        NotificationType.JOB_MATCHED: TypeSpec(
            group=EventGroup.JOB_MATCHES, priority=Priority.P2, channels=BOT
        ),
        NotificationType.RESPONSE_RECEIVED: TypeSpec(
            group=EventGroup.RESPONSES, priority=Priority.P1, channels=BOT_AND_APP
        ),
        NotificationType.RESPONSE_ACCEPTED: TypeSpec(
            group=EventGroup.RESPONSES,
            priority=Priority.P0,
            channels=BOT_AND_APP,
            quiet_exempt=True,
        ),
        NotificationType.RESPONSE_NOT_SELECTED: TypeSpec(
            group=EventGroup.RESPONSES, priority=Priority.P3, channels=BOT_AND_APP
        ),
        NotificationType.JOB_INVITED: TypeSpec(
            group=EventGroup.RESPONSES, priority=Priority.P1, channels=BOT_AND_APP
        ),
        NotificationType.MESSAGE_RECEIVED: TypeSpec(
            group=EventGroup.MESSAGES,
            priority=Priority.P0,
            channels=BOT_AND_APP,
            quiet_exempt=True,
        ),
        NotificationType.DEAL_PROPOSED: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P0, channels=BOT_AND_APP, quiet_exempt=True
        ),
        NotificationType.DEAL_CANCELLED: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P1, channels=BOT_AND_APP
        ),
        NotificationType.DISPUTE_OPENED: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P0, channels=BOT_AND_APP
        ),
        NotificationType.DEAL_REMINDER: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P1, channels=BOT
        ),
        NotificationType.DEAL_COMPLETION_PROMPT: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P1, channels=BOT
        ),
        NotificationType.REVIEW_REQUEST: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P2, channels=BOT
        ),
        NotificationType.REVIEW_PUBLISHED: TypeSpec(
            group=EventGroup.DEALS, priority=Priority.P3, channels=BOT_AND_APP
        ),
        NotificationType.MODERATION_DECISION: TypeSpec(
            group=EventGroup.ACCOUNT, priority=Priority.P1, channels=BOT_AND_APP
        ),
        NotificationType.JOB_EXPIRING: TypeSpec(
            group=EventGroup.RESPONSES, priority=Priority.P3, channels=BOT
        ),
        NotificationType.JOB_EXPIRED: TypeSpec(
            group=EventGroup.RESPONSES, priority=Priority.P3, channels=BOT_AND_APP
        ),
        NotificationType.PROFILE_STALE_REMINDER: TypeSpec(
            group=EventGroup.JOB_MATCHES, priority=Priority.P3, channels=BOT
        ),
        NotificationType.ACCOUNT_RESTRICTED: TypeSpec(
            group=EventGroup.ACCOUNT, priority=Priority.P0, channels=BOT_AND_APP
        ),
    }
)
