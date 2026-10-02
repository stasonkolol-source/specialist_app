"""Схемы HTTP deals (ARCHITECTURE §8.5): сделка стороне и отмена с причиной."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.deals.application.dto import DealView
from app.modules.deals.domain.deal import (
    PARTY_CANCEL_REASONS,
    DealCancelReason,
    DealOrigin,
    DealPriceType,
    DealRole,
    DealStatus,
)
from app.modules.deals.errors import InvalidDealError
from app.platform.http.money import MoneyOut
from app.platform.kernel.ids import UserId
from app.platform.kernel.money import Currency, Money


class DealPriceOut(BaseModel):
    """Договорённая цена: «3 500 RSD», «от 3 500 RSD», «3 500 RSD/час», «Договорная»."""

    type: DealPriceType | None
    amount: MoneyOut | None


class DealOut(BaseModel):
    """Сделка стороне (S26): кто я в ней, условия и вехи для таймлайна."""

    id: UUID
    status: DealStatus
    origin: DealOrigin
    my_role: DealRole
    title: str
    category_id: int | None
    price: DealPriceOut
    scheduled_at: datetime | None
    client_id: UUID
    performer_id: UUID
    profile_id: UUID | None = Field(description="Профиль специалиста исполнителя (S08)")
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None
    awaits_my_confirmation: bool = Field(
        description="«Договорились» предложила вторая сторона: подтвердить или отклонить"
    )
    i_marked_done: bool = Field(description="Я уже отметил «Работа выполнена»")
    other_marked_done: bool = Field(description="Вторая сторона отметила «Работа выполнена»")
    agreed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by_me: bool | None = Field(description="Отменил я; None — не отменена или система")
    cancel_reason: DealCancelReason | None
    version: int
    created_at: datetime

    @classmethod
    def of(cls, deal: DealView, viewer_id: UserId) -> DealOut:
        role = deal.role_of(viewer_id)
        if role is None:  # чужую сделку use case не отдаёт
            raise ValueError("viewer is not a party")
        client = role is DealRole.CLIENT
        mine = deal.client_confirmed_at if client else deal.performer_confirmed_at
        other = deal.performer_confirmed_at if client else deal.client_confirmed_at
        cancelled_by_me = None
        if deal.status is DealStatus.CANCELLED and deal.cancelled_by is not None:
            cancelled_by_me = deal.cancelled_by == viewer_id
        amount = deal.agreed_price
        return cls(
            id=deal.id,
            status=deal.status,
            origin=deal.origin,
            my_role=role,
            title=deal.title,
            category_id=deal.category_id,
            price=DealPriceOut(
                type=deal.price_type,
                amount=MoneyOut.of(Money(amount, Currency.RSD)) if amount is not None else None,
            ),
            scheduled_at=deal.scheduled_at,
            client_id=deal.client_id,
            performer_id=deal.performer_id,
            profile_id=deal.profile_id,
            job_id=deal.job_id,
            response_id=deal.response_id,
            conversation_id=deal.conversation_id,
            awaits_my_confirmation=(
                deal.status is DealStatus.PROPOSED
                and deal.proposed_by is not None
                and deal.proposed_by != viewer_id
            ),
            i_marked_done=mine is not None,
            other_marked_done=other is not None,
            agreed_at=deal.agreed_at,
            completed_at=deal.completed_at,
            cancelled_at=deal.cancelled_at,
            cancelled_by_me=cancelled_by_me,
            cancel_reason=deal.cancel_reason,
            version=deal.version,
            created_at=deal.created_at,
        )


class DealsPageOut(BaseModel):
    items: list[DealOut]
    next_cursor: str | None


class DealCancelIn(BaseModel):
    reason: DealCancelReason = Field(
        description="plans_changed, no_agreement, no_contact или other; остальные ставит система"
    )

    def cancel_reason(self) -> DealCancelReason:
        if self.reason not in PARTY_CANCEL_REASONS:
            raise InvalidDealError(field="reason", reason="not_allowed")
        return self.reason
