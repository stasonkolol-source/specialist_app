"""BFF «Сделки и отзывы» S28 (DEVELOPMENT_PLAN 7.3): свои сделки в обеих ролях из deals, вторая
сторона — имя на карточке специалиста (specialists) или имя аккаунта (identity), отзыв по сделке
и до когда его можно оставить (reviews). Новые первыми, курсор; группы «Активные» и
«Завершённые» собирает экран.
"""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.interfaces.http.views.deal import (
    DealCancelCause,
    DealCardPriceOut,
    DealPriceKind,
    DealReviewOut,
    DealSide,
    DealState,
)
from app.interfaces.http.views.specialist import _money
from app.modules.deals.api import DealsApi, DealSummary
from app.modules.identity.api import IdentityApi
from app.modules.reviews.api import DealRef, ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import DEFAULT_LIMIT, PageRequest
from app.platform.kernel.principal import Principal

HISTORY_LIMIT = 50

router = APIRouter(tags=["views"])


class HistoryCounterpartOut(BaseModel):
    id: UUID
    role: DealSide = Field(description="Кто вторая сторона для меня")
    display_name: str = Field(description="Аккаунт удалён — пусто")


class HistoryDealOut(BaseModel):
    id: UUID
    status: DealState
    my_role: DealSide
    title: str
    price: DealCardPriceOut
    scheduled_at: datetime | None
    counterpart: HistoryCounterpartOut
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by_me: bool | None = Field(description="Отменил я; None — не отменена или система")
    cancel_reason: DealCancelCause | None
    created_at: datetime
    my_review: DealReviewOut | None = Field(description="Свой отзыв по сделке")
    review_until: datetime | None = Field(
        description="Клиент может оставить отзыв до этого времени; null — нельзя или уже оставлен"
    )


class HistoryPageOut(BaseModel):
    items: list[HistoryDealOut]
    next_cursor: str | None


@router.get("/me/deal-history", response_model=HistoryPageOut, dependencies=AUTHENTICATED)
@inject
async def list_deal_history(
    *,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=HISTORY_LIMIT)] = DEFAULT_LIMIT,
    principal: FromDishka[Principal],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
    specialists: FromDishka[SpecialistsApi],
    reviews: FromDishka[ReviewsApi],
) -> HistoryPageOut:
    """Свои сделки (S28): клиентом и исполнителем, со второй стороной и отзывом."""
    viewer = principal.user_id
    page = await deals.my_deals(viewer, PageRequest(limit=limit, cursor=cursor))
    others = {_other(deal, viewer) for deal in page.items}
    users = await identity.users(others)
    profiles = await specialists.profiles_of(others)
    states = await reviews.review_states(
        viewer,
        [
            DealRef(
                id=deal.id,
                client_id=deal.client_id,
                status=deal.status,
                completed_at=deal.completed_at,
            )
            for deal in page.items
        ],
    )
    items: list[HistoryDealOut] = []
    for deal in page.items:
        other = _other(deal, viewer)
        user, profile = users.get(other), profiles.get(other)
        alive = user is not None and not user.is_deleted
        name = ""
        if alive and user is not None:
            performer = deal.my_role == "client"
            card_name = profile.display_name if performer and profile is not None else None
            name = card_name or user.display_name
        state = states.get(deal.id)
        mine = state.mine if state is not None else None
        items.append(
            HistoryDealOut(
                id=deal.id,
                status=cast(DealState, deal.status),
                my_role=cast(DealSide, deal.my_role),
                title=deal.title,
                price=DealCardPriceOut(
                    type=cast(DealPriceKind | None, deal.price_type),
                    amount=_money(deal.agreed_price),
                ),
                scheduled_at=deal.scheduled_at,
                counterpart=HistoryCounterpartOut(
                    id=other,
                    role="performer" if deal.my_role == "client" else "client",
                    display_name=name,
                ),
                completed_at=deal.completed_at,
                cancelled_at=deal.cancelled_at,
                cancelled_by_me=(
                    deal.cancelled_by == viewer
                    if deal.status == "cancelled" and deal.cancelled_by is not None
                    else None
                ),
                cancel_reason=cast(DealCancelCause | None, deal.cancel_reason),
                created_at=deal.created_at,
                my_review=(
                    DealReviewOut(id=mine.id, status=mine.status, rating=mine.rating)
                    if mine is not None
                    else None
                ),
                review_until=state.open_until if state is not None else None,
            )
        )
    return HistoryPageOut(items=items, next_cursor=page.next_cursor)


def _other(deal: DealSummary, viewer: UserId) -> UserId:
    return deal.performer_id if deal.client_id == viewer else deal.client_id
