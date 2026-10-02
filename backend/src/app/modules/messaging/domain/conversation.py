"""Диалог (DEVELOPMENT_PLAN 6.3a; ARCHITECTURE §11.5, ADR-0010): переписка клиента и исполнителя.

- `job_response` — по отклику на заявку: один диалог на отклик; первое сообщение — сам отклик
  (предложение с ценой и «когда смогу»). Начинает клиент или исполнитель этого отклика;
- `direct` — прямое обращение клиента к специалисту из карточки: один диалог на пару.

Участники — клиент и исполнитель; чужой диалог — как несуществующий (404). Писать можно в
открытый диалог; закрытый и заблокированный (жалобы, 4.7) — только читать. Прочитанное — по
последнему сообщению, которое участник видел.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.messaging.errors import (
    CannotStartConversationError,
    ConversationClosedError,
    ConversationNotFoundError,
)
from app.platform.contracts.events.messaging import ConversationStarted
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import UserId


class ConversationKind(StrEnum):
    JOB_RESPONSE = "job_response"
    DIRECT = "direct"
    SUPPORT = "support"
    """Поддержка (после MVP)."""


class ConversationStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    BLOCKED = "blocked"
    """Заблокирован участником или модерацией (4.7)."""


class ParticipantRole(StrEnum):
    CLIENT = "client"
    PERFORMER = "performer"
    SUPPORT = "support"


@dataclass(kw_only=True)
class Participant:
    user_id: UserId
    role: ParticipantRole
    last_read_message_id: UUID | None = None


@dataclass(eq=False, kw_only=True)
class Conversation(AggregateRoot):
    id: UUID
    kind: ConversationKind
    status: ConversationStatus
    client: Participant
    performer: Participant
    created_at: datetime
    job_id: UUID | None = None
    response_id: UUID | None = None
    deal_id: UUID | None = None
    last_message_at: datetime | None = None
    _new: bool = field(default=False, repr=False, compare=False)

    @classmethod
    def for_response(
        cls,
        *,
        conversation_id: UUID,
        client_id: UserId,
        performer_id: UserId,
        initiator_id: UserId,
        job_id: UUID,
        response_id: UUID,
        now: datetime,
    ) -> Conversation:
        """Диалог по отклику: начинает клиент заявки или исполнитель отклика."""
        return cls._start(
            conversation_id=conversation_id,
            kind=ConversationKind.JOB_RESPONSE,
            client_id=client_id,
            performer_id=performer_id,
            initiator_id=initiator_id,
            job_id=job_id,
            response_id=response_id,
            now=now,
        )

    @classmethod
    def direct(
        cls,
        *,
        conversation_id: UUID,
        client_id: UserId,
        performer_id: UserId,
        now: datetime,
    ) -> Conversation:
        """Прямое обращение клиента к специалисту из его карточки (S08)."""
        return cls._start(
            conversation_id=conversation_id,
            kind=ConversationKind.DIRECT,
            client_id=client_id,
            performer_id=performer_id,
            initiator_id=client_id,
            job_id=None,
            response_id=None,
            now=now,
        )

    @property
    def is_new(self) -> bool:
        """Создан сейчас: репозиторий вставит строку, use case — первое сообщение отклика."""
        return self._new

    def participant(self, user_id: UserId) -> Participant:
        """Участник диалога; не участник — как несуществующий диалог (404)."""
        if user_id == self.client.user_id:
            return self.client
        if user_id == self.performer.user_id:
            return self.performer
        raise ConversationNotFoundError(conversation_id=self.id)

    def counterpart(self, user_id: UserId) -> Participant:
        """Вторая сторона для участника."""
        mine = self.participant(user_id)
        return self.performer if mine is self.client else self.client

    def ensure_writable(self, sender_id: UserId) -> Participant:
        """Писать может участник открытого диалога."""
        sender = self.participant(sender_id)
        if self.status is not ConversationStatus.OPEN:
            raise ConversationClosedError(
                conversation_id=self.id, conversation_status=self.status.value
            )
        return sender

    def message_posted(self, *, sender_id: UserId, message_id: UUID, now: datetime) -> None:
        """Новое сообщение: время последнего и прочитанное у автора — его собственное."""
        self.participant(sender_id).last_read_message_id = message_id
        self.last_message_at = now

    def system_posted(self, now: datetime) -> None:
        """Системное сообщение (о сделке): диалог поднимается в списке."""
        self.last_message_at = now

    def link_deal(self, deal_id: UUID) -> None:
        """Сделка диалога: «Договорились» здесь или выбор отклика этого диалога. По ней —
        открыты ли контакты."""
        self.deal_id = deal_id

    def read(self, user_id: UserId, message_id: UUID) -> bool:
        """Участник дочитал до сообщения; более раннее, чем уже прочитанное, — ничего."""
        reader = self.participant(user_id)
        known = reader.last_read_message_id
        if known is not None and known >= message_id:  # UUIDv7 растёт со временем
            return False
        reader.last_read_message_id = message_id
        return True

    @classmethod
    def _start(
        cls,
        *,
        conversation_id: UUID,
        kind: ConversationKind,
        client_id: UserId,
        performer_id: UserId,
        initiator_id: UserId,
        job_id: UUID | None,
        response_id: UUID | None,
        now: datetime,
    ) -> Conversation:
        if client_id == performer_id:
            raise CannotStartConversationError(reason="self")
        if initiator_id not in (client_id, performer_id):
            raise CannotStartConversationError(reason="not_a_party")
        conversation = cls(
            id=conversation_id,
            kind=kind,
            status=ConversationStatus.OPEN,
            client=Participant(user_id=client_id, role=ParticipantRole.CLIENT),
            performer=Participant(user_id=performer_id, role=ParticipantRole.PERFORMER),
            created_at=now,
            job_id=job_id,
            response_id=response_id,
        )
        conversation._new = True
        conversation._record(
            ConversationStarted(
                conversation_id=conversation_id,
                kind=kind.value,
                initiator_id=initiator_id,
                client_id=client_id,
                performer_id=performer_id,
                job_id=job_id,
                response_id=response_id,
                occurred_at=now,
            )
        )
        return conversation

    def mark_persisted(self) -> None:
        """Строка вставлена. Вызывает только репозиторий."""
        self._new = False
