"""События модуля deals (ADR-0020 §2; ARCHITECTURE §7.9; DEVELOPMENT_PLAN 6.1a). Подписчики:
jobs (заявка «в работе», отменённая — снова открыта, завершённая — завершена), identity
(уровень доверия по завершённым сделкам), уведомления (6.1b, 6.3b), переписка (6.3b),
аналитика; споры (6.1c) — модерация (кейс `dispute`), уведомления и аналитика."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DealProposed(DomainEvent):
    """«Договорились» в чате одной стороной (6.3b): вторая подтверждает или отклоняет за 72 ч."""

    event_type = "deals.DealProposed"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    proposed_by: UserId
    conversation_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealAgreed(DomainEvent):
    """Стороны договорились: клиент выбрал отклик или вторая сторона подтвердила «Договорились»."""

    event_type = "deals.DealAgreed"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    """DealOrigin: `job_response`, `direct`, `chat`."""
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCompleted(DomainEvent):
    """Работа выполнена: обе стороны подтвердили (или одна и 72 ч без возражений, 6.1b)."""

    event_type = "deals.DealCompleted"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None
    auto: bool = False
    """Завершила система: одна сторона отметила «выполнено», вторая молчала 72 ч (6.1b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealReminderDue(DomainEvent):
    """До времени сделки 2 ч: сторонам — напоминание `deal.reminder` (6.1b)."""

    event_type = "deals.DealReminderDue"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    scheduled_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCompletionDue(DomainEvent):
    """Время сделки прошло: «Работа выполнена?» `deal.completion_prompt` тем, кто ещё не
    отметил (6.1b)."""

    event_type = "deals.DealCompletionDue"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    ask_client: bool
    ask_performer: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class DealMarkedDone(DomainEvent):
    """Одна сторона отметила «Работа выполнена», вторая ещё нет (7.3, B2): второй стороне —
    «Работа выполнена?» сразу, не дожидаясь срока; молчит 72 ч — сделка завершится сама."""

    event_type = "deals.DealMarkedDone"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    marked_by: str
    """DealRole отметившей стороны: `client` или `performer`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCancelled(DomainEvent):
    """Сделку отменили: сторона с причиной, система (истекло предложение, удалён аккаунт) или
    модератор по спору (6.1c: `cancelled_by` — `moderator`, причина — `dispute`)."""

    event_type = "deals.DealCancelled"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None
    cancelled_by: str
    """DealRole отменившей стороны (`client`, `performer`), `system` или `moderator` (спор,
    6.1c): от этого зависит, кем становится выбранный отклик — «отклонён» клиентом или «отозван»
    исполнителем (§7.9)."""
    reason: str
    proposal: bool = False
    """Отменили предложение «Договорились» (S53), а не сделку: до подтверждения сделки не было —
    в чате и в боте «Предложение не принято», а не «отменил сделку» (UX_GUIDANCE №14)."""
    conversation_id: UUID | None = None
    """Диалог, где договаривались (сделка из чата): кнопка «Открыть чат» уведомления."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealDisputed(DomainEvent):
    """Сторона открыла спор по идущей сделке (6.1c, S52): модерация открывает кейс `dispute`
    (P1, угрозы — P0), второй стороне — `dispute.opened` и 48 ч на ответ, аналитика —
    `dispute_opened`."""

    event_type = "deals.DealDisputed"
    deal_id: DealId
    dispute_id: UUID
    client_id: UserId
    performer_id: UserId
    opened_by: UserId
    respondent_id: UserId
    kind: str
    """DisputeKind: `no_show`, `quality`, `prepayment_taken`, `damage`, `safety`, `other`."""
    origin: str
    category_id: CategoryId | None
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None
    respond_by: datetime
    """До этого вторая сторона отвечает (48 ч)."""
    media_ids: tuple[UUID, ...] = ()
    """Фото-доказательства открывшего: legal hold, пока кейс открыт."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeAnswered(DomainEvent):
    """Вторая сторона ответила на спор: ответ и его фото — в кейс модерации."""

    event_type = "deals.DisputeAnswered"
    deal_id: DealId
    dispute_id: UUID
    opened_by: UserId
    respondent_id: UserId
    media_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeUnanswered(DomainEvent):
    """48 ч прошло без ответа второй стороны (`deals.dispute_response_sla`): кейс помечается
    «нет ответа» — модератор решает без него."""

    event_type = "deals.DisputeUnanswered"
    deal_id: DealId
    dispute_id: UUID
    opened_by: UserId
    respondent_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeWithdrawn(DomainEvent):
    """Открывший отозвал спор: сделка снова идёт, кейс модерации закрывается без решения."""

    event_type = "deals.DisputeWithdrawn"
    deal_id: DealId
    dispute_id: UUID
    opened_by: UserId
    respondent_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeResolved(DomainEvent):
    """Модератор решил спор (moderation ResolveDispute): сделка завершена или отменена, обеим
    сторонам — `dispute.resolved` (statement of reasons)."""

    event_type = "deals.DisputeResolved"
    deal_id: DealId
    dispute_id: UUID
    client_id: UserId
    performer_id: UserId
    opened_by: UserId
    outcome: str
    """`completed` или `cancelled` — каким стал статус сделки."""
    reason_code: str
    """Машинный код причины решения (`no_show`, `work_done`, …): текст — в уведомлении."""
