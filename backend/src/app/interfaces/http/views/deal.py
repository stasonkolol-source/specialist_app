"""BFF сделки S26 (DEVELOPMENT_PLAN 6.2): сделка из deals, заявка из jobs (район, окно времени,
отклик; точный адрес — владельцу и выбранному исполнителю, правило jobs), вторая сторона:
исполнитель — профиль specialists, фото media и рейтинг reviews, клиент — имя identity.

Только сторонам: чужая сделка — 404 `deal_not_found`. Вехи таймлайна — отклик, выбор, отметки
«Работа выполнена» обеих сторон, завершение или отмена; чат сделки (messaging) и когда пора
«Работа выполнена» — главной кнопкой S26 (UX_GUIDANCE №2). Отзыв (7.2): свой — статус и оценка;
клиенту завершённой сделки — до когда его можно оставить. Спор (6.1c, S52): последний спор
сделки — что случилось и чьё, срок ответа, ответ, решение; фото обеих сторон — presigned GET
приватного бакета на 5 минут (только сторонам). Форма — как ответ `POST /deals/{id}/dispute…`:
экран кладёт его в кэш карточки без перечитывания.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Final, Literal, cast
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import (
    CardNamedOut,
    CardPhotoOut,
    CardVariantOut,
    _money,
    _photo,
    _visible_cards,
)
from app.modules.deals.api import DealsApi, DealSummary, DisputeSummary
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import DealJob, JobsApi
from app.modules.media.api import MediaApi, MediaRef
from app.modules.messaging.api import MessagingApi
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.http.money import MoneyOut
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import CityId, DealId, DistrictId, MediaId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["views"])
OPEN: Final = frozenset({"agreed", "disputed", "completed"})
"""Договорились: Telegram второй стороны виден (S43, 6.5) — и под спором (6.1c): спор открывают
только по договорённости."""
DealPath = Annotated[UUID, Path(description="id сделки")]

DealState = Literal["proposed", "agreed", "completed", "cancelled", "disputed"]
DealOriginKind = Literal["job_response", "direct", "chat"]
DealSide = Literal["client", "performer"]
DealPriceKind = Literal["fixed", "from", "hourly", "negotiable"]
DealCancelCause = Literal[
    "plans_changed", "no_agreement", "no_contact", "other", "expired", "account_deleted", "dispute"
]
DisputeState = Literal["open", "answered", "no_response", "resolved", "withdrawn"]
DisputeCause = Literal["no_show", "quality", "prepayment_taken", "damage", "safety", "other"]
DisputeVerdict = Literal["completed", "cancelled"]


class DealCardPriceOut(BaseModel):
    type: DealPriceKind | None
    amount: MoneyOut | None


class DealCounterpartOut(BaseModel):
    role: DealSide = Field(description="Кто вторая сторона для меня")
    display_name: str = Field(description="Аккаунт удалён — пусто")
    profile_id: UUID | None = Field(description="Профиль специалиста исполнителя (S08)")
    avatar: CardPhotoOut | None
    rating: float | None = Field(description="Когда отзывов достаточно; иначе is_new")
    rating_count: int
    is_new: bool = Field(description="«Новый специалист» — у исполнителя без трёх отзывов")
    phone_verified: bool
    telegram: str | None = Field(
        description="«@username» после договорённости, если вторая сторона его показывает (S43)"
    )


class DealPointOut(BaseModel):
    lat: float
    lon: float


class DealPlaceOut(BaseModel):
    city: CardNamedOut | None
    district: CardNamedOut | None
    address: str | None = Field(description="Только владельцу и выбранному исполнителю")
    point: DealPointOut | None = Field(description="Точная точка — тем же")


class DealTimelineOut(BaseModel):
    responded_at: datetime | None = Field(description="Отклик на заявку")
    agreed_at: datetime | None = Field(description="Выбран исполнителем / договорились")
    my_mark_at: datetime | None = Field(description="Я отметил «Работа выполнена»")
    other_mark_at: datetime | None = Field(description="Вторая сторона отметила")
    completed_at: datetime | None
    cancelled_at: datetime | None


class DealReviewOut(BaseModel):
    id: UUID
    status: str = Field(description="under_review | published | removed")
    rating: int


class DealCardDisputePhotoOut(BaseModel):
    id: UUID
    placeholder: str | None
    variants: list[CardVariantOut] = Field(
        description="presigned GET на 5 минут; до обработки — []"
    )


class DealCardDisputeOut(BaseModel):
    """Спор по сделке стороне (S52): та же форма, что ответ `POST /deals/{id}/dispute…`."""

    id: UUID
    deal_id: UUID
    deal_status: DealState
    status: DisputeState = Field(
        description="open — ждём ответа, answered, no_response — 48 ч без ответа, resolved,"
        " withdrawn"
    )
    kind: DisputeCause
    opened_by_me: bool
    description: str
    photos: list[DealCardDisputePhotoOut]
    respond_by: datetime
    response: str | None
    response_photos: list[DealCardDisputePhotoOut]
    responded_at: datetime | None
    unanswered_at: datetime | None
    withdrawn_at: datetime | None
    outcome: DisputeVerdict | None
    reason_code: str | None
    resolved_at: datetime | None
    created_at: datetime


class DealCardOut(BaseModel):
    id: UUID
    status: DealState
    origin: DealOriginKind
    my_role: DealSide
    title: str
    price: DealCardPriceOut
    scheduled_at: datetime | None = Field(description="Договорённое время")
    preferred_from: datetime | None = Field(description="Окно времени из заявки")
    preferred_to: datetime | None
    urgency: str | None = Field(description="Срочность заявки: asap, today, this_week, flexible")
    availability_note: str | None = Field(description="«Когда смогу» из отклика")
    budget: MoneyOut | None = Field(description="Бюджет заявки «от» — для сравнения с ценой")
    counterpart: DealCounterpartOut
    place: DealPlaceOut
    timeline: DealTimelineOut
    awaits_my_confirmation: bool = Field(description="«Договорились» предложила вторая сторона")
    cancelled_by_me: bool | None = Field(description="Отменил я; None — не отменена или система")
    cancel_reason: DealCancelCause | None
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None = Field(
        description="Чат сделки — «Написать» (S30): где договорились или по выбранному отклику"
    )
    version: int
    proposed_at: datetime | None = Field(description="«Договорились» предложено тогда (S53)")
    proposal_expires_at: datetime | None = Field(
        description="Предложение отменится, если не ответить до этого времени (72 ч)"
    )
    completion_due_at: datetime | None = Field(
        description="Идущей сделке: с этого времени «Работа выполнена» — главная кнопка (бот"
        " спрашивает «Работа выполнена?»); раньше — «Написать»"
    )
    my_review: DealReviewOut | None = Field(description="Свой отзыв по сделке (7.2)")
    review_until: datetime | None = Field(
        description="Клиент может оставить отзыв до этого времени (14 дней после завершения);"
        " null — нельзя или уже оставлен"
    )
    dispute: DealCardDisputeOut | None = Field(
        description="Последний спор по сделке (S52): идущий, решённый или отозванный"
    )


@router.get("/deals/{deal_id:uuid}/card", response_model=DealCardOut, dependencies=AUTHENTICATED)
@inject
async def get_deal_card(
    *,
    deal_id: DealPath,
    principal: FromDishka[Principal],
    deals: FromDishka[DealsApi],
    jobs: FromDishka[JobsApi],
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    media: FromDishka[MediaApi],
    reviews: FromDishka[ReviewsApi],
    geo: FromDishka[GeoApi],
    messaging: FromDishka[MessagingApi],
    locale: FromDishka[Locale],
) -> DealCardOut:
    """Сделка стороне (S26): условия, вторая сторона, место и вехи; чужая — 404."""
    viewer = principal.user_id
    deal = await deals.deal_card(DealId(deal_id), viewer)
    # чат сделки по выбранному отклику знает messaging: сделка из отклика его id не хранит
    conversation_id = deal.conversation_id or await messaging.deal_conversation(
        deal.id, deal.response_id
    )
    job = await jobs.deal_job(deal.job_id, deal.response_id, viewer) if deal.job_id else None
    client = deal.my_role == "client"
    if client:
        counterpart = await _performer(deal, specialists, identity, media, reviews)
    else:
        counterpart = await _client(deal, identity)
    if deal.status in OPEN:
        other_id = deal.performer_id if client else deal.client_id
        contacts = await identity.telegram_contacts([other_id])
        counterpart = counterpart.model_copy(update={"telegram": contacts.get(other_id)})
    mine = deal.client_confirmed_at if client else deal.performer_confirmed_at
    other = deal.performer_confirmed_at if client else deal.client_confirmed_at
    cancelled_by_me = None
    if deal.status == "cancelled" and deal.cancelled_by is not None:
        cancelled_by_me = deal.cancelled_by == viewer
    review = await reviews.review_state(
        deal.id,
        viewer,
        client_id=deal.client_id,
        status=deal.status,
        completed_at=deal.completed_at,
    )
    dispute = deal.dispute
    return DealCardOut(
        id=deal.id,
        status=cast(DealState, deal.status),
        origin=cast(DealOriginKind, deal.origin),
        my_role=cast(DealSide, deal.my_role),
        title=deal.title,
        price=DealCardPriceOut(
            type=cast(DealPriceKind | None, deal.price_type), amount=_money(deal.agreed_price)
        ),
        scheduled_at=deal.scheduled_at,
        preferred_from=job.preferred_from if job is not None else None,
        preferred_to=job.preferred_to if job is not None else None,
        urgency=job.urgency if job is not None else None,
        availability_note=job.availability_note if job is not None else None,
        budget=_money(job.budget_min) if job is not None else None,
        counterpart=counterpart,
        place=await _place(job, geo, locale),
        timeline=DealTimelineOut(
            responded_at=job.responded_at if job is not None else None,
            agreed_at=deal.agreed_at,
            my_mark_at=mine,
            other_mark_at=other,
            completed_at=deal.completed_at,
            cancelled_at=deal.cancelled_at,
        ),
        proposed_at=deal.created_at if deal.status == "proposed" else None,
        proposal_expires_at=deal.proposal_expires_at,
        completion_due_at=deal.completion_due_at,
        awaits_my_confirmation=(
            deal.status == "proposed"
            and deal.proposed_by is not None
            and deal.proposed_by != viewer
        ),
        cancelled_by_me=cancelled_by_me,
        cancel_reason=cast(DealCancelCause | None, deal.cancel_reason),
        job_id=deal.job_id,
        response_id=deal.response_id,
        conversation_id=conversation_id,
        version=deal.version,
        my_review=(
            DealReviewOut(id=review.mine.id, status=review.mine.status, rating=review.mine.rating)
            if review.mine is not None
            else None
        ),
        review_until=review.open_until,
        dispute=await _dispute(dispute, deal, viewer, media) if dispute is not None else None,
    )


async def _dispute(
    dispute: DisputeSummary, deal: DealSummary, viewer: UUID, media: MediaApi
) -> DealCardDisputeOut:
    """Спор стороне: фото обеих сторон — сторонам сделки (карточку чужой сделки не отдаём)."""
    refs = await media.refs([*dispute.media_ids, *dispute.response_media_ids])
    return DealCardDisputeOut(
        id=dispute.id,
        deal_id=dispute.deal_id,
        deal_status=cast(DealState, deal.status),
        status=cast(DisputeState, dispute.status),
        kind=cast(DisputeCause, dispute.kind),
        opened_by_me=dispute.opened_by == viewer,
        description=dispute.description,
        photos=_evidence(dispute.media_ids, refs),
        respond_by=dispute.respond_by,
        response=dispute.response,
        response_photos=_evidence(dispute.response_media_ids, refs),
        responded_at=dispute.responded_at,
        unanswered_at=dispute.unanswered_at,
        withdrawn_at=dispute.withdrawn_at,
        outcome=cast(DisputeVerdict | None, dispute.outcome),
        reason_code=dispute.reason_code,
        resolved_at=dispute.resolved_at,
        created_at=dispute.created_at,
    )


def _evidence(
    media_ids: tuple[MediaId, ...], refs: Mapping[MediaId, MediaRef]
) -> list[DealCardDisputePhotoOut]:
    """Фото по порядку; удалённые и сбойные не показываем, обрабатываемые — без вариантов."""
    return [
        DealCardDisputePhotoOut(
            id=ref.id,
            placeholder=ref.placeholder,
            variants=[
                CardVariantOut(name=v.name, url=v.url, width=v.width, height=v.height)
                for v in ref.variants
            ],
        )
        for media_id in media_ids
        if (ref := refs.get(media_id)) is not None and not ref.broken
    ]


async def _performer(
    deal: DealSummary,
    specialists: SpecialistsApi,
    identity: IdentityApi,
    media: MediaApi,
    reviews: ReviewsApi,
) -> DealCounterpartOut:
    """Исполнитель — клиенту: опубликованный профиль с фото и рейтингом; без профиля (подработка,
    скрыт) — имя аккаунта. Профиль — карточкой: описания и портфолио экрану не нужны."""
    user = await identity.get_user(deal.performer_id)
    alive = user is not None and not user.is_deleted
    account_name = user.display_name if user is not None and alive else ""
    profile = None
    if deal.profile_id is not None:
        cards = await _visible_cards([deal.profile_id], specialists, identity)
        profile = cards.get(deal.profile_id)
    rating = (await reviews.summaries([profile.id])).get(profile.id) if profile else None
    avatar = None
    if profile is not None and profile.avatar_media_id is not None:
        refs = await media.refs([profile.avatar_media_id])
        avatar = _photo(refs.get(profile.avatar_media_id))
    name = profile.display_name if profile is not None else account_name
    return DealCounterpartOut(
        role="performer",
        display_name=name if alive else "",
        profile_id=profile.id if profile is not None else None,
        avatar=avatar if alive else None,
        rating=None if rating is None or rating.is_new else rating.mean,
        rating_count=rating.count if rating is not None else 0,
        is_new=rating is None or rating.is_new,
        phone_verified=bool(alive and user is not None and user.phone_verified),
        telegram=None,
    )


async def _client(deal: DealSummary, identity: IdentityApi) -> DealCounterpartOut:
    """Клиент — исполнителю: имя из аккаунта и «Телефон подтверждён»."""
    user = await identity.get_user(deal.client_id)
    alive = user is not None and not user.is_deleted
    return DealCounterpartOut(
        role="client",
        display_name=user.display_name if alive and user is not None else "",
        profile_id=None,
        avatar=None,
        rating=None,
        rating_count=0,
        is_new=False,
        phone_verified=bool(alive and user is not None and user.phone_verified),
        telegram=None,
    )


async def _place(job: DealJob | None, geo: GeoApi, locale: Locale) -> DealPlaceOut:
    if job is None:
        return DealPlaceOut(city=None, district=None, address=None, point=None)
    city = await geo.city(CityId(job.city_id))
    district = await geo.district(DistrictId(job.district_id)) if job.district_id else None
    return DealPlaceOut(
        city=CardNamedOut(id=city.id, name=city.name.get(locale)) if city else None,
        district=CardNamedOut(id=district.id, name=district.name.get(locale)) if district else None,
        address=job.address,
        point=DealPointOut(lat=job.point.lat, lon=job.point.lon) if job.point else None,
    )
