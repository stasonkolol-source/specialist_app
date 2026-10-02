"""Сообщение (DEVELOPMENT_PLAN 6.3a; ARCHITECTURE §11.5): текст участника, предложение из отклика
или системное. Простая запись (ADR-0020 §5): правила — у диалога и при составлении текста.

До договорённости (`agreed`) телефоны, ссылки, e-mail и @username заменяются «•••» детектором
`platform/text` — хранится уже скрытый текст, а в `payload` — отметка `masked`: Mini App
показывает «контакты откроются после договорённости». Просьба о предоплате — отметка
`prepayment`: под сообщением баннер безопасности. Модерация проверяет текст после отправки:
нарушение скрывает сообщение (`hidden`).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.messaging.errors import InvalidMessageError
from app.platform.kernel.ids import UserId
from app.platform.text.contact_masking import find_prepayment, mask_contacts

MAX_BODY: Final = 4000
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

    @property
    def payload(self) -> dict[str, object]:
        flags: dict[str, object] = {}
        if self.masked:
            flags["masked"] = True
        if self.prepayment:
            flags["prepayment"] = True
        return flags


def compose(text: str, *, contacts_locked: bool) -> Composed:
    """Текст участника: обрезанный по краям, 1–4000 символов; до договорённости контакты
    скрыты, просьба о предоплате отмечена."""
    body = text.strip()
    if not 1 <= len(body) <= MAX_BODY:
        raise InvalidMessageError(field="body", reason="length")
    masked = mask_contacts(body) if contacts_locked else body
    return Composed(body=masked, masked=masked != body, prepayment=find_prepayment(body))


def check_client_id(value: str | None) -> str | None:
    """Ключ идемпотентности с клиента: пустой — нет ключа; длиннее 64 — ошибка."""
    if value is None or not value.strip():
        return None
    if len(value) > MAX_CLIENT_ID:
        raise InvalidMessageError(field="client_msg_id", reason="too_long")
    return value.strip()
