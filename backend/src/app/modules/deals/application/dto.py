"""Сделка и спор для чтения (S25, S26, S52, списки сделок): всё, что хранит строка."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.deals.domain.deal import (
    DealCancelReason,
    DealOrigin,
    DealPriceType,
    DealRole,
    DealStatus,
)
from app.modules.deals.domain.dispute import (
    ACTIVE,
    DisputeId,
    DisputeKind,
    DisputeOutcome,
    DisputeStatus,
)
from app.platform.kernel.ids import CategoryId, DealId, MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DealView:
    id: DealId
    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    origin: DealOrigin
    status: DealStatus
    title: str
    category_id: CategoryId | None
    price_type: DealPriceType | None
    agreed_price: int | None
    """Пара."""
    scheduled_at: datetime | None
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None
    proposed_by: UserId | None
    agreed_at: datetime | None
    client_confirmed_at: datetime | None
    performer_confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: UserId | None
    cancel_reason: DealCancelReason | None
    version: int
    created_at: datetime
    updated_at: datetime

    def role_of(self, user_id: UserId) -> DealRole | None:
        if user_id == self.client_id:
            return DealRole.CLIENT
        if user_id == self.performer_id:
            return DealRole.PERFORMER
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeView:
    id: DisputeId
    deal_id: DealId
    opened_by: UserId
    respondent_id: UserId
    kind: DisputeKind
    description: str
    media_ids: tuple[MediaId, ...]
    respond_by: datetime
    status: DisputeStatus
    response: str | None
    response_media_ids: tuple[MediaId, ...]
    responded_at: datetime | None
    unanswered_at: datetime | None
    withdrawn_at: datetime | None
    outcome: DisputeOutcome | None
    reason_code: str | None
    resolved_by: UserId | None
    resolved_at: datetime | None
    created_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE
