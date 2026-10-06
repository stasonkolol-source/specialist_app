"""Сообщение (DEVELOPMENT_PLAN 6.3a, 6.3b; ARCHITECTURE §11.5): текст участника, предложение из
отклика, контакт после договорённости или системное (что со сделкой). Простая запись (ADR-0020
§5): правила — у диалога и при составлении текста.

До договорённости (`agreed`) телефоны, ссылки, e-mail и @username заменяются «•••» детектором
`platform/text` — хранится уже скрытый текст, а в `payload` — отметка `masked`: Mini App
показывает «контакты откроются после договорённости». Просьба о предоплате — отметка
`prepayment`: под сообщением баннер безопасности. Модерация проверяет текст после отправки:
нарушение скрывает сообщение (`hidden`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.messaging.errors import InvalidMessageError
from app.platform.kernel.ids import UserId
from app.platform.text.contact_masking import (
    find_contacts,
    find_prepayment,
    find_split_contacts,
    mask_findings,
)

MAX_BODY: Final = 4000
SPLIT_WINDOW: Final = timedelta(minutes=2)
SPLIT_MESSAGES: Final = 3
"""Номер или ник по частям (QA ADV-06): новое сообщение проверяется вместе с тремя последними
сообщениями того же отправителя в диалоге за две минуты."""
MAX_CLIENT_ID: Final = 64
"""`client_msg_id` — ключ идемпотентности отправки с клиента (UUID или своя строка)."""


class MessageKind(StrEnum):
    TEXT = "text"
    MEDIA = "media"
    SYSTEM = "system"
    CONTACT_SHARE = "contact_share"
    OFFER = "offer"
    """Предложение из отклика — первое сообщение диалога по отклику."""


class MessageModeration(StrEnum):
    OK = "ok"
    FLAGGED = "flagged"
    HIDDEN = "hidden"
    """Нарушение: текст скрыт от второй стороны."""


class ContactType(StrEnum):
    """Чем делятся после договорённости (S54): username Telegram или телефон."""

    TELEGRAM = "telegram"
    PHONE = "phone"


class SystemEvent(StrEnum):
    """Системное сообщение в ленте диалога: что случилось со сделкой (6.3b)."""

    DEAL_PROPOSED = "deal_proposed"
    DEAL_AGREED = "deal_agreed"
    DEAL_CANCELLED = "deal_cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class Message:
    id: UUID
    conversation_id: UUID
    sender_id: UserId | None
    """None — системное сообщение."""
    kind: MessageKind
    body: str | None
    created_at: datetime
    client_msg_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    moderation: MessageModeration = MessageModeration.OK


@dataclass(frozen=True, slots=True, kw_only=True)
class Composed:
    """Текст сообщения к отправке: что хранить и какие отметки."""

    body: str
    masked: bool
    prepayment: bool
    earlier: tuple[str, ...] = ()
    """Прежние сообщения окна (`recent` в `compose`) со скрытыми частями контакта — по порядку;
    изменившиеся переписываются в хранилище."""

    @property
    def payload(self) -> dict[str, object]:
        flags: dict[str, object] = {}
        if self.masked:
            flags["masked"] = True
        if self.prepayment:
            flags["prepayment"] = True
        return flags


def compose(text: str, *, contacts_locked: bool, recent: Sequence[str] = ()) -> Composed:
    """Текст участника: обрезанный по краям, 1–4000 символов; до договорённости контакты
    скрыты, просьба о предоплате отмечена. `recent` — прежние тексты отправителя в окне
    (SPLIT_WINDOW): контакт, разбитый на несколько сообщений, скрывается и в новом, и в прежних
    (`earlier`) — QA ADV-06."""
    body = text.strip()
    if not 1 <= len(body) <= MAX_BODY:
        raise InvalidMessageError(field="body", reason="length")
    prepayment = find_prepayment(body)
    if not contacts_locked:
        return Composed(body=body, masked=False, prepayment=prepayment)
    *before, split = find_split_contacts([*recent, body])
    masked = mask_findings(body, (*find_contacts(body), *split))
    return Composed(
        body=masked,
        masked=masked != body,
        prepayment=prepayment,
        earlier=tuple(
            mask_findings(part, found) for part, found in zip(recent, before, strict=True)
        ),
    )


def check_client_id(value: str | None) -> str | None:
    """Ключ идемпотентности с клиента: пустой — нет ключа; длиннее 64 — ошибка."""
    if value is None or not value.strip():
        return None
    if len(value) > MAX_CLIENT_ID:
        raise InvalidMessageError(field="client_msg_id", reason="too_long")
    return value.strip()


def system_message(
    *,
    message_id: UUID,
    conversation_id: UUID,
    event: SystemEvent,
    deal_id: UUID,
    now: datetime,
    **details: str,
) -> Message:
    """Системное сообщение о сделке. Ключ `<событие>:<сделка>` в `client_msg_id`: повтор задачи
    второго такого же не запишет."""
    return Message(
        id=message_id,
        conversation_id=conversation_id,
        sender_id=None,
        kind=MessageKind.SYSTEM,
        body=None,
        created_at=now,
        client_msg_id=f"{event.value}:{deal_id}",
        payload={"event": event.value, "deal_id": str(deal_id), **details},
    )
