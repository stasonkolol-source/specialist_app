"""Спор по сделке (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §7.9, §14.4; ADR-0016, ADR-0017).

Эскроу нет: спор — медиация. Сторона идущей сделки сообщает о проблеме (S52): что случилось,
описание и фото-доказательства (media `dispute`, приватный бакет). Сделка — `disputed`: ни
«Работа выполнена», ни отмена, ни сроки 6.1b её не трогают. Вторая сторона получает 48 ч на
ответ; молчит — спор помечается «нет ответа» (`deals.dispute_response_sla`), и модератор решает
без неё. Решение модератора (moderation ResolveDispute, через фасад) завершает или отменяет
сделку; открывший может отозвать спор, пока решения нет, — сделка снова идёт.

Жизненный цикл:
    open → answered | no_response → resolved
    open | answered | no_response → withdrawn | resolved
    no_response → answered            (поздний ответ модератору тоже пригодится)
У сделки один идущий спор: следующий — только после отзыва или решения прежнего.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.deals.domain.deal import Deal, DealStatus
from app.modules.deals.errors import DisputeStateError, InvalidDisputeError
from app.platform.contracts.events.deals import (
    DealDisputed,
    DisputeAnswered,
    DisputeResolved,
    DisputeUnanswered,
    DisputeWithdrawn,
)
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.errors import ProgrammingError
from app.platform.kernel.ids import DealId, MediaId, UserId

DisputeId = NewType("DisputeId", UUID)

RESPONSE_WINDOW: Final = timedelta(hours=48)
"""Вторая сторона отвечает в течение 48 ч (§14.4)."""
MAX_TEXT: Final = 2000
"""Описание и ответ — как отзыв: хватает на рассказ, не хватает на простыню."""
MAX_PHOTOS: Final = 6
"""Фото-доказательств у каждой стороны — как фото заявки."""
MAX_REASON_CODE: Final = 64
"""Как у решения модерации: код причины решения — машинный (`no_show`, `work_done`)."""


class DisputeKind(StrEnum):
    """Что случилось (S52)."""

    NO_SHOW = "no_show"
    """Не пришёл."""
    QUALITY = "quality"
    """Сделал плохо или не то."""
    PREPAYMENT_TAKEN = "prepayment_taken"
    """Взял предоплату или просит больше."""
    DAMAGE = "damage"
    """Ущерб имуществу."""
    SAFETY = "safety"
    """Ущерб, грубость или угрозы: кейс — в очередь безопасности P0."""
    OTHER = "other"


class DisputeStatus(StrEnum):
    OPEN = "open"
    """Ждём ответа второй стороны (48 ч)."""
    ANSWERED = "answered"
    NO_RESPONSE = "no_response"
    """48 ч прошло без ответа: модератор решает без него."""
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"


ACTIVE: Final = frozenset({DisputeStatus.OPEN, DisputeStatus.ANSWERED, DisputeStatus.NO_RESPONSE})
"""Спор идёт: сделка `disputed`, удаление аккаунта сторон и доказательства — под legal hold."""
AWAITS_ANSWER: Final = frozenset({DisputeStatus.OPEN, DisputeStatus.NO_RESPONSE})


class DisputeOutcome(StrEnum):
    """Решение модератора — каким становится статус сделки."""

    COMPLETED = "completed"
    """Работа выполнена: сделка завершена, отзыв клиенту доступен."""
    CANCELLED = "cancelled"
    """Сделка отменена: заявка снова открыта."""


@dataclass(eq=False, kw_only=True)
class Dispute(VersionedAggregate):
    id: DisputeId
    deal_id: DealId
    opened_by: UserId
    respondent_id: UserId
    """Вторая сторона: о ней спор, ей — 48 ч на ответ и, если нужно, санкция."""
    kind: DisputeKind
    description: str
    media_ids: tuple[MediaId, ...]
    respond_by: datetime
    status: DisputeStatus
    created_at: datetime
    updated_at: datetime
    response: str | None = None
    response_media_ids: tuple[MediaId, ...] = ()
    responded_at: datetime | None = None
    unanswered_at: datetime | None = None
    """Срок ответа вышел (пометка «нет ответа» в кейсе)."""
    withdrawn_at: datetime | None = None
    outcome: DisputeOutcome | None = None
    reason_code: str | None = None
    resolved_by: UserId | None = None
    resolved_at: datetime | None = None

    @classmethod
    def open(
        cls,
        *,
        dispute_id: DisputeId,
        deal: Deal,
        actor_id: UserId,
        kind: DisputeKind,
        description: str,
        media_ids: tuple[MediaId, ...],
        now: datetime,
    ) -> Dispute:
        """Сторона идущей сделки сообщает о проблеме: сделка — `disputed` (DealDisputed)."""
        text = _text(description, field="description")
        photos = _photos(media_ids)
        deal.open_dispute(actor_id=actor_id, now=now)
        respondent = deal.performer_id if actor_id == deal.client_id else deal.client_id
        dispute = cls(
            id=dispute_id,
            deal_id=deal.id,
            opened_by=actor_id,
            respondent_id=respondent,
            kind=kind,
            description=text,
            media_ids=photos,
            respond_by=now + RESPONSE_WINDOW,
            status=DisputeStatus.OPEN,
            created_at=now,
            updated_at=now,
            version=1,
        )
        dispute._record(
            DealDisputed(
                deal_id=deal.id,
                dispute_id=dispute_id,
                client_id=deal.client_id,
                performer_id=deal.performer_id,
                opened_by=actor_id,
                respondent_id=respondent,
                kind=kind.value,
                origin=deal.origin.value,
                category_id=deal.terms.category_id,
                job_id=deal.job_id,
                response_id=deal.response_id,
                conversation_id=deal.conversation_id,
                respond_by=dispute.respond_by,
                media_ids=photos,
                occurred_at=now,
            )
        )
        return dispute

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    def respond(
        self, *, actor_id: UserId, text: str, media_ids: tuple[MediaId, ...], now: datetime
    ) -> None:
        """Ответ второй стороны — один; после срока тоже принимается, пока нет решения."""
        if actor_id != self.respondent_id:
            raise DisputeStateError(dispute_status=self.status.value, reason="not_respondent")
        if self.status not in AWAITS_ANSWER:
            raise DisputeStateError(dispute_status=self.status.value, reason="not_awaiting")
        self.response = _text(text, field="response")
        self.response_media_ids = _photos(media_ids)
        self.responded_at = self.updated_at = now
        self.status = DisputeStatus.ANSWERED
        self._record(
            DisputeAnswered(
                deal_id=self.deal_id,
                dispute_id=self.id,
                opened_by=self.opened_by,
                respondent_id=self.respondent_id,
                media_ids=self.response_media_ids,
                occurred_at=now,
            )
        )

    def withdraw(self, *, deal: Deal, actor_id: UserId, now: datetime) -> None:
        """Открывший отзывает спор, пока нет решения: сделка снова идёт."""
        self._of(deal)
        if actor_id != self.opened_by:
            raise DisputeStateError(dispute_status=self.status.value, reason="not_opener")
        if not self.is_active:
            raise DisputeStateError(dispute_status=self.status.value, reason="closed")
        deal.resume_after_dispute(actor_id=actor_id, now=now)
        self.status = DisputeStatus.WITHDRAWN
        self.withdrawn_at = self.updated_at = now
        self._record(
            DisputeWithdrawn(
                deal_id=self.deal_id,
                dispute_id=self.id,
                opened_by=self.opened_by,
                respondent_id=self.respondent_id,
                occurred_at=now,
            )
        )

    def mark_unanswered(self, *, now: datetime) -> bool:
        """Срок ответа вышел — «нет ответа», один раз. Ответили, отозвали, решили или рано —
        False."""
        if self.status is not DisputeStatus.OPEN or self.respond_by > now:
            return False
        self.status = DisputeStatus.NO_RESPONSE
        self.unanswered_at = self.updated_at = now
        self._record(
            DisputeUnanswered(
                deal_id=self.deal_id,
                dispute_id=self.id,
                opened_by=self.opened_by,
                respondent_id=self.respondent_id,
                occurred_at=now,
            )
        )
        return True

    def resolve(
        self,
        *,
        deal: Deal,
        outcome: DisputeOutcome,
        reason_code: str,
        moderator_id: UserId | None,
        now: datetime,
    ) -> None:
        """Решение модератора: сделка завершена или отменена (DealCompleted / DealCancelled),
        сторонам — statement of reasons (DisputeResolved)."""
        self._of(deal)
        if not self.is_active:
            raise DisputeStateError(dispute_status=self.status.value, reason="closed")
        if not 0 < len(reason_code) <= MAX_REASON_CODE:
            raise InvalidDisputeError(field="reason_code", reason="length")
        deal.settle_dispute(target=DealStatus(outcome.value), moderator_id=moderator_id, now=now)
        self.status = DisputeStatus.RESOLVED
        self.outcome, self.reason_code = outcome, reason_code
        self.resolved_by, self.resolved_at, self.updated_at = moderator_id, now, now
        self._record(
            DisputeResolved(
                deal_id=deal.id,
                dispute_id=self.id,
                client_id=deal.client_id,
                performer_id=deal.performer_id,
                opened_by=self.opened_by,
                outcome=outcome.value,
                reason_code=reason_code,
                occurred_at=now,
            )
        )

    def _of(self, deal: Deal) -> None:
        if deal.id != self.deal_id:  # ошибка вызывающего: спор другой сделки
            raise ProgrammingError(f"dispute {self.id} is not of deal {deal.id}")


def _text(value: str, *, field: str) -> str:
    text = value.strip()
    if not text:
        raise InvalidDisputeError(field=field, reason="empty")
    if len(text) > MAX_TEXT:
        raise InvalidDisputeError(field=field, reason="too_long")
    return text


def _photos(media_ids: tuple[MediaId, ...]) -> tuple[MediaId, ...]:
    photos = tuple(dict.fromkeys(media_ids))
    if len(photos) > MAX_PHOTOS:
        raise InvalidDisputeError(field="media_ids", reason="too_many")
    return photos
