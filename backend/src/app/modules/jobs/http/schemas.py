"""Схемы HTTP jobs (ARCHITECTURE §8.5): заявка на входе и на выходе, карточка ленты, отклики,
шаблоны откликов и подписки на новые заявки (5.7).

Суммы — в пара (1 RSD = 100 пара), наружу — `MoneyOut`. Точная точка и адрес — только
владельцу (`viewer_role: owner`); гость и исполнитель видят район и смещённую точку (§7.6).
Названия категорий и районов клиент берёт из справочников: в ответе — их id.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.jobs.application.alerts import AlertItem
from app.modules.jobs.application.content import JobDraft
from app.modules.jobs.application.dto import MyResponseRef
from app.modules.jobs.application.feed import JobCard, Photo
from app.modules.jobs.application.responses import (
    MyResponse,
    OwnerResponse,
    ResponseGroup,
    ResponseJob,
    TodayQuota,
)
from app.modules.jobs.application.use_cases.list_job_responses import JobResponse
from app.modules.jobs.application.use_cases.show_job import JobClient, JobDetails
from app.modules.jobs.domain.alert import (
    MAX_ALERT_CATEGORIES,
    MAX_ALERT_DISTRICTS,
    MAX_ALERT_LANGUAGES,
    MAX_ALERTS,
    MAX_RADIUS_M,
    MIN_RADIUS_M,
    AlertCriteria,
    AlertDelivery,
)
from app.modules.jobs.domain.invite import MAX_INVITES, Invite
from app.modules.jobs.domain.job import (
    MAX_ADDRESS,
    MAX_BUDGET,
    MAX_DESCRIPTION,
    MAX_PHOTOS,
    MAX_TITLE,
    MIN_TITLE,
    Budget,
    BudgetType,
    BudgetUnit,
    CloseReason,
    JobStatus,
    Urgency,
    Visibility,
)
from app.modules.jobs.domain.response import (
    MAX_AVAILABILITY,
    MAX_MESSAGE,
    MAX_PRICE,
    Offer,
    ResponsePriceType,
    ResponseReview,
    ResponseStatus,
)
from app.modules.jobs.domain.template import MAX_TEMPLATE_TITLE, MAX_TEMPLATES, ResponseTemplate
from app.modules.jobs.errors import InvalidResponseError, InvalidTemplateError
from app.platform.http.fields import (
    CategoryIdIn,
    CityIdIn,
    CleanText,
    DistrictIdIn,
    OptionalCleanText,
)
from app.platform.http.money import MoneyOut
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId
from app.platform.kernel.money import Currency, Money

MAX_LANGUAGES = 4
JobLanguage = Literal["ru", "sr", "en", "uk"]
"""Языки общения заявки — как у профиля специалиста (specialists `Language`): другой код —
422, а не мусор в заявке и фильтре ленты. Подписку проверяет домен (`invalid_job_alert`)."""
ViewerRole = Literal["owner", "viewer"]


class JobPointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class JobPointOut(BaseModel):
    lat: float
    lon: float


class JobIn(BaseModel):
    title: CleanText = Field(min_length=MIN_TITLE, max_length=MAX_TITLE)
    description: CleanText = Field(default="", max_length=MAX_DESCRIPTION)
    category_id: CategoryIdIn = Field(description="Услуга (лист каталога), где включены заявки")
    urgency: Urgency
    budget_type: BudgetType
    budget_min: int | None = Field(default=None, ge=1, le=MAX_BUDGET, description="Пара")
    budget_max: int | None = Field(default=None, ge=1, le=MAX_BUDGET, description="Пара")
    budget_unit: BudgetUnit = BudgetUnit.WORK
    city_id: CityIdIn
    district_id: DistrictIdIn | None = None
    point: JobPointIn | None = Field(
        default=None, description="Точная точка: видит только выбранный исполнитель"
    )
    address_private: OptionalCleanText = Field(
        default=None, max_length=MAX_ADDRESS, description="Подъезд и этаж — тоже только ему"
    )
    preferred_from: datetime | None = None
    preferred_to: datetime | None = None
    languages: list[JobLanguage] = Field(default_factory=list, max_length=MAX_LANGUAGES)
    media_ids: list[UUID] = Field(default_factory=list, max_length=MAX_PHOTOS)

    def draft(self, content_lang: str) -> JobDraft:
        return JobDraft(
            title=self.title,
            description=self.description,
            category_id=CategoryId(self.category_id),
            urgency=self.urgency,
            budget=Budget(
                type=self.budget_type,
                min=self.budget_min,
                max=self.budget_max,
                unit=self.budget_unit,
            ),
            city_id=CityId(self.city_id),
            content_lang=content_lang,
            district_id=DistrictId(self.district_id) if self.district_id is not None else None,
            point=GeoPoint(lat=self.point.lat, lon=self.point.lon) if self.point else None,
            address_private=self.address_private or None,
            preferred_from=self.preferred_from,
            preferred_to=self.preferred_to,
            languages=tuple(self.languages),
            media_ids=tuple(MediaId(media) for media in self.media_ids),
        )


class JobCloseIn(BaseModel):
    reason: Literal["hired_here", "hired_elsewhere", "not_needed", "no_suitable"]


class JobPhotoOut(BaseModel):
    url: str
    width: int
    height: int
    placeholder: str | None = Field(description="ThumbHash (base64) для мгновенного превью")

    @classmethod
    def of(cls, photo: Photo) -> JobPhotoOut:
        return cls(
            url=photo.url, width=photo.width, height=photo.height, placeholder=photo.placeholder
        )


class JobClientOut(BaseModel):
    """Блок клиента S15: «Елена К. · в «Соседях» 3 месяца · 2 заявки»."""

    display_name: str
    member_since: datetime
    jobs_count: int = Field(description="Сколько заявок клиента публиковалось")
    phone_verified: bool

    @classmethod
    def of(cls, client: JobClient) -> JobClientOut:
        return cls(
            display_name=client.display_name,
            member_since=client.member_since,
            jobs_count=client.jobs_count,
            phone_verified=client.phone_verified,
        )


class MyResponseRefOut(BaseModel):
    id: UUID
    status: ResponseStatus
    review: ResponseReview = Field(description="pending — на проверке, blocked — скрыт модерацией")

    @classmethod
    def of(cls, ref: MyResponseRef) -> MyResponseRefOut:
        return cls(id=ref.id, status=ref.status, review=ref.review)


class JobOut(BaseModel):
    id: UUID
    viewer_role: ViewerRole = Field(description="owner — своя заявка; viewer — гость, исполнитель")
    status: JobStatus
    visibility: Visibility
    title: str
    description: str
    content_lang: str
    category_id: int
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: MoneyOut | None
    budget_max: MoneyOut | None
    budget_unit: BudgetUnit
    city_id: int
    district_id: int | None
    point_public: JobPointOut | None = Field(description="Смещённая на 300–500 м точка")
    point_exact: JobPointOut | None = Field(description="Владельцу и выбранному исполнителю")
    address_private: str | None = Field(description="Владельцу и выбранному исполнителю")
    languages: list[str]
    media_ids: list[UUID]
    photos: list[JobPhotoOut] = Field(description="Готовые фото, вариант md (800 px)")
    client: JobClientOut | None = Field(description="Блок клиента; null — аккаунт удалён")
    max_responses: int
    responses_count: int
    my_response: MyResponseRefOut | None = Field(
        description="Свой отклик исполнителя — «Вы откликнулись» на S15; гостю и владельцу — null"
    )
    extensions_count: int = Field(description="Сколько раз продлевали: не больше трёх")
    views_count: int | None = Field(description="Просмотры (S23) — владельцу; остальным — null")
    notified_count: int | None = Field(
        description="Скольким подписчикам заявка ушла — сразу или подборкой (S21, 5.7) — владельцу"
    )
    new_responses: int | None = Field(
        description="Отклики, которых владелец ещё не видел (бейдж S22); остальным — null"
    )
    moderation_note: str | None = Field(description="Причина отказа модерации — владельцу")
    version: int
    created_at: datetime
    published_at: datetime | None
    expires_at: datetime | None
    closed_at: datetime | None
    close_reason: CloseReason | None

    @classmethod
    def of(cls, details: JobDetails, *, owner: bool) -> JobOut:
        job = details.job
        mine = details.my_response
        exact = owner or (mine is not None and mine.status is ResponseStatus.ACCEPTED)
        return cls(
            id=job.id,
            viewer_role="owner" if owner else "viewer",
            status=job.status,
            visibility=job.visibility,
            title=job.title,
            description=job.description,
            content_lang=job.content_lang,
            category_id=job.category_id,
            urgency=job.urgency,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
            budget_type=job.budget_type,
            budget_min=_money(job.budget_min),
            budget_max=_money(job.budget_max),
            budget_unit=job.budget_unit,
            city_id=job.city_id,
            district_id=job.district_id,
            point_public=_point(job.point_public),
            point_exact=_point(job.point_exact) if exact else None,
            address_private=job.address_private if exact else None,
            languages=list(job.languages),
            media_ids=list(job.media_ids),
            photos=[JobPhotoOut.of(photo) for photo in details.photos],
            client=JobClientOut.of(details.client) if details.client else None,
            max_responses=job.max_responses,
            responses_count=job.responses_count,
            my_response=MyResponseRefOut.of(details.my_response) if details.my_response else None,
            extensions_count=job.extensions_count,
            views_count=job.views_count if owner else None,
            notified_count=job.notified_count if owner else None,
            new_responses=details.new_responses if owner else None,
            moderation_note=job.moderation_note if owner else None,
            version=job.version,
            created_at=job.created_at,
            published_at=job.published_at,
            expires_at=job.expires_at,
            closed_at=job.closed_at,
            close_reason=job.close_reason,
        )


class JobsOut(BaseModel):
    items: list[JobOut]


class JobCardOut(BaseModel):
    """Карточка ленты S13: начало описания, превью фото, место и счётчик откликов."""

    id: UUID
    title: str
    description: str = Field(description="Начало описания — до 280 знаков, дальше «…»")
    category_id: int
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: MoneyOut | None
    budget_max: MoneyOut | None
    budget_unit: BudgetUnit
    district_id: int | None
    distance_m: int | None = Field(description="До точки зрителя, шагом 100 м; без точки — null")
    photos: list[JobPhotoOut] = Field(description="До трёх превью (thumb)")
    photos_count: int
    responses_count: int
    max_responses: int
    published_at: datetime

    @classmethod
    def of(cls, card: JobCard) -> JobCardOut:
        item = card.item
        return cls(
            id=item.id,
            title=item.title,
            description=item.description,
            category_id=item.category_id,
            urgency=item.urgency,
            preferred_from=item.preferred_from,
            preferred_to=item.preferred_to,
            budget_type=item.budget_type,
            budget_min=_money(item.budget_min),
            budget_max=_money(item.budget_max),
            budget_unit=item.budget_unit,
            district_id=item.district_id,
            distance_m=item.distance_m,
            photos=[JobPhotoOut.of(photo) for photo in card.photos],
            photos_count=item.photos_count,
            responses_count=item.responses_count,
            max_responses=item.max_responses,
            published_at=item.published_at,
        )


class JobsPageOut(BaseModel):
    items: list[JobCardOut]
    next_cursor: str | None


class JobsCountOut(BaseModel):
    count: int


class SavedJobsOut(BaseModel):
    """Сохранённые заявки S12: открытые, новые сохранения первыми, не больше ста."""

    items: list[JobCardOut]


def _money(amount: int | None) -> MoneyOut | None:
    return MoneyOut.of(Money(amount, Currency.RSD)) if amount is not None else None


def _point(point: GeoPoint | None) -> JobPointOut | None:
    return JobPointOut(lat=point.lat, lon=point.lon) if point is not None else None


class ResponseOfferIn(BaseModel):
    """Предложение исполнителя S16: сообщение клиенту, цена и «когда смогу»."""

    message: CleanText = Field(min_length=1, max_length=MAX_MESSAGE)
    price_type: ResponsePriceType
    price_amount: int | None = Field(
        default=None, ge=1, le=MAX_PRICE, description="Пара; у договорной — нет"
    )
    availability_note: OptionalCleanText = Field(
        default=None, max_length=MAX_AVAILABILITY, description="«Сегодня, 19:00»"
    )

    def offer(self) -> Offer:
        return Offer(
            message=self.message,
            price_type=self.price_type,
            price_amount=self.price_amount,
            availability_note=self.availability_note,
        )


class ResponseIn(ResponseOfferIn):
    """Отклик S16; собранный из шаблона — с его id."""

    template_id: UUID | None = Field(
        default=None, description="Свой шаблон, из которого отклик (S16, кнопка бота); чужой — 404"
    )


class ResponsePriceOut(BaseModel):
    type: ResponsePriceType
    amount: MoneyOut | None

    @classmethod
    def of(cls, offer: Offer) -> ResponsePriceOut:
        return cls(type=offer.price_type, amount=_money(offer.price_amount))


class ResponseJobOut(BaseModel):
    """Заявка в карточке «Мои отклики» S17."""

    id: UUID
    title: str
    status: JobStatus
    category_id: int
    city_id: int
    district_id: int | None
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: MoneyOut | None
    budget_max: MoneyOut | None
    budget_unit: BudgetUnit
    responses_count: int
    max_responses: int
    published_at: datetime | None

    @classmethod
    def of(cls, job: ResponseJob) -> ResponseJobOut:
        return cls(
            id=job.id,
            title=job.title,
            status=job.status,
            category_id=job.category_id,
            city_id=job.city_id,
            district_id=job.district_id,
            urgency=job.urgency,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
            budget_type=job.budget_type,
            budget_min=_money(job.budget_min),
            budget_max=_money(job.budget_max),
            budget_unit=job.budget_unit,
            responses_count=job.responses_count,
            max_responses=job.max_responses,
            published_at=job.published_at,
        )


class MyResponseOut(BaseModel):
    """Свой отклик (S17): статус, проверка, предложение и заявка."""

    id: UUID
    status: ResponseStatus
    review: ResponseReview = Field(description="pending — на проверке, blocked — скрыт модерацией")
    message: str
    price: ResponsePriceOut
    availability_note: str | None
    is_first: bool = Field(description="Первый отклик на заявку — «Первый отклик»")
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    job: ResponseJobOut

    @classmethod
    def of(cls, response: MyResponse) -> MyResponseOut:
        return cls(
            id=response.id,
            status=response.status,
            review=response.review,
            message=response.offer.message,
            price=ResponsePriceOut.of(response.offer),
            availability_note=response.offer.availability_note,
            is_first=response.is_first,
            created_at=response.created_at,
            updated_at=response.updated_at,
            decided_at=response.decided_at,
            job=ResponseJobOut.of(response.job),
        )


class ResponseCountsOut(BaseModel):
    """Числа на чипах S17: «Все 3 · Активные 2 · Выбран 1 · Не выбран 1 · Архив»."""

    all: int
    active: int
    accepted: int
    not_selected: int
    archive: int

    @classmethod
    def of(cls, counts: dict[ResponseGroup, int]) -> ResponseCountsOut:
        return cls(
            all=sum(counts.values()),
            active=counts.get(ResponseGroup.ACTIVE, 0),
            accepted=counts.get(ResponseGroup.ACCEPTED, 0),
            not_selected=counts.get(ResponseGroup.NOT_SELECTED, 0),
            archive=counts.get(ResponseGroup.ARCHIVE, 0),
        )


class TodayOut(BaseModel):
    """«Сегодня откликов: 3 из 50 — лимит по уровню доверия» (S17)."""

    used: int
    limit: int

    @classmethod
    def of(cls, today: TodayQuota) -> TodayOut:
        return cls(used=today.used, limit=today.limit)


class MyResponsesPageOut(BaseModel):
    items: list[MyResponseOut]
    next_cursor: str | None
    counts: ResponseCountsOut
    today: TodayOut


class ResponsePerformerOut(BaseModel):
    user_id: UUID
    display_name: str = Field(description="Аккаунт удалён — пусто")
    profile_id: UUID | None = Field(description="Профиль специалиста; без него — подработка")


class JobResponseOut(BaseModel):
    """Отклик на свою заявку (S23): прошедший проверку."""

    id: UUID
    status: ResponseStatus
    performer: ResponsePerformerOut
    message: str
    price: ResponsePriceOut
    availability_note: str | None
    is_first: bool = Field(description="«Откликнулся первым»")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, listed: JobResponse) -> JobResponseOut:
        response: OwnerResponse = listed.response
        return cls(
            id=response.id,
            status=response.status,
            performer=ResponsePerformerOut(
                user_id=response.performer_id,
                display_name=listed.performer_name,
                profile_id=response.profile_id,
            ),
            message=response.offer.message,
            price=ResponsePriceOut.of(response.offer),
            availability_note=response.offer.availability_note,
            is_first=response.is_first,
            created_at=response.created_at,
            updated_at=response.updated_at,
        )


class JobResponsesOut(BaseModel):
    items: list[JobResponseOut]


class ResponseTemplateIn(ResponseOfferIn):
    """Новый шаблон S57 или «Сохранить как шаблон» на S16."""

    title: CleanText = Field(
        min_length=1, max_length=MAX_TEMPLATE_TITLE, description="«Могу сегодня»"
    )

    def offer(self) -> Offer:
        with _as_template_error():
            return super().offer()


class ResponseTemplatePatchIn(BaseModel):
    """Правка шаблона S57 — что прислано. Предложение меняется целиком: `message` и `price_type`
    вместе (без `price_amount` — суммы нет). `primary: true` — «Сделать основным»: шаблон
    становится первым."""

    title: OptionalCleanText = Field(default=None, min_length=1, max_length=MAX_TEMPLATE_TITLE)
    message: OptionalCleanText = Field(default=None, min_length=1, max_length=MAX_MESSAGE)
    price_type: ResponsePriceType | None = None
    price_amount: int | None = Field(default=None, ge=1, le=MAX_PRICE)
    availability_note: OptionalCleanText = Field(default=None, max_length=MAX_AVAILABILITY)
    primary: bool = False

    @model_validator(mode="after")
    def _whole_offer(self) -> ResponseTemplatePatchIn:
        sent = self.model_fields_set & _OFFER_FIELDS
        if sent and (self.message is None or self.price_type is None):
            raise ValueError("message and price_type go together")
        return self

    def offer(self) -> Offer | None:
        if self.message is None or self.price_type is None:
            return None
        with _as_template_error():
            return Offer(
                message=self.message,
                price_type=self.price_type,
                price_amount=self.price_amount,
                availability_note=self.availability_note,
            )


@contextmanager
def _as_template_error() -> Iterator[None]:
    """Неверное предложение в шаблоне — «Проверьте шаблон», а не «Проверьте отклик»."""
    try:
        yield
    except InvalidResponseError as error:
        raise InvalidTemplateError(**error.params) from error


_OFFER_FIELDS = frozenset({"message", "price_type", "price_amount", "availability_note"})


class ResponseTemplateOut(BaseModel):
    id: UUID
    title: str
    message: str
    price: ResponsePriceOut
    availability_note: str | None
    primary: bool = Field(description="Основной — первый: S16 подставляет его сразу")
    updated_at: datetime

    @classmethod
    def of(cls, template: ResponseTemplate) -> ResponseTemplateOut:
        return cls(
            id=template.id,
            title=template.title,
            message=template.offer.message,
            price=ResponsePriceOut.of(template.offer),
            availability_note=template.offer.availability_note,
            primary=template.primary,
            updated_at=template.updated_at,
        )


class ResponseTemplatesOut(BaseModel):
    items: list[ResponseTemplateOut] = Field(description="По порядку, первый — основной")
    limit: int = Field(description="Сколько шаблонов можно: «1 из 2» на S57")

    @classmethod
    def of(cls, templates: list[ResponseTemplate]) -> ResponseTemplatesOut:
        return cls(items=[ResponseTemplateOut.of(t) for t in templates], limit=MAX_TEMPLATES)


class InvitesIn(BaseModel):
    """Кого пригласить в заявку (S21, S23): профили специалистов из каталога."""

    profile_ids: list[UUID] = Field(min_length=1, max_length=MAX_INVITES)


class JobInviteOut(BaseModel):
    profile_id: UUID
    invited_at: datetime


class JobInvitesOut(BaseModel):
    items: list[JobInviteOut] = Field(description="По порядку приглашения")
    limit: int = Field(description="Сколько можно пригласить в одну заявку")

    @classmethod
    def of(cls, invites: list[Invite]) -> JobInvitesOut:
        return cls(
            items=[
                JobInviteOut(profile_id=invite.profile_id, invited_at=invite.invited_at)
                for invite in invites
            ],
            limit=MAX_INVITES,
        )


class AcceptedOut(BaseModel):
    """Отклик выбран (S25): заявка «в работе» и созданная сделка — экран сделки S26."""

    deal_id: UUID
    job: JobOut


M_IN_KM = 1000


class JobAlertCriteriaIn(BaseModel):
    """Условия подписки (S19): районы или точка с радиусом, ни того ни другого — весь город."""

    category_ids: list[CategoryIdIn] = Field(
        min_length=1,
        max_length=MAX_ALERT_CATEGORIES,
        description="Разделы и услуги каталога: заявки в них и в их подкатегориях",
    )
    city_id: CityIdIn
    district_ids: list[DistrictIdIn] = Field(default_factory=list, max_length=MAX_ALERT_DISTRICTS)
    center: JobPointIn | None = Field(
        default=None, description="Точка подписчика для радиуса: видна только ему"
    )
    radius_km: float | None = Field(
        default=None, ge=MIN_RADIUS_M / M_IN_KM, le=MAX_RADIUS_M / M_IN_KM
    )
    min_budget: int | None = Field(
        default=None, ge=1, le=MAX_BUDGET, description="Пара: бюджет заявки не меньше"
    )
    urgencies: list[Urgency] = Field(default_factory=list, description="Пусто — любые")
    languages: list[str] = Field(
        default_factory=list, max_length=MAX_ALERT_LANGUAGES, description="Пусто — любые"
    )

    def criteria(self) -> AlertCriteria:
        center = self.center
        return AlertCriteria(
            category_ids=tuple(CategoryId(item) for item in self.category_ids),
            city_id=CityId(self.city_id),
            district_ids=tuple(DistrictId(item) for item in self.district_ids),
            center=GeoPoint(lat=center.lat, lon=center.lon) if center is not None else None,
            radius_m=round(self.radius_km * M_IN_KM) if self.radius_km is not None else None,
            min_budget=self.min_budget,
            urgencies=tuple(self.urgencies),
            languages=tuple(self.languages),
        )


class JobAlertIn(BaseModel):
    criteria: JobAlertCriteriaIn
    delivery: AlertDelivery = Field(
        default=AlertDelivery.INSTANT, description="Сразу или подборкой раз в день"
    )


class JobAlertPatchIn(BaseModel):
    """Правка подписки: условия целиком (S19), режим, переключатель S18 — что прислано."""

    criteria: JobAlertCriteriaIn | None = None
    delivery: AlertDelivery | None = None
    is_active: bool | None = Field(default=None, description="Включить — значит и снять паузу")


class JobAlertCriteriaOut(BaseModel):
    category_ids: list[int]
    city_id: int
    district_ids: list[int]
    center: JobPointOut | None
    radius_km: float | None
    min_budget: int | None = Field(description="Пара")
    urgencies: list[Urgency]
    languages: list[str]

    @classmethod
    def of(cls, criteria: AlertCriteria) -> JobAlertCriteriaOut:
        center = criteria.center
        return cls(
            category_ids=list(criteria.category_ids),
            city_id=criteria.city_id,
            district_ids=list(criteria.district_ids),
            center=JobPointOut(lat=center.lat, lon=center.lon) if center is not None else None,
            radius_km=criteria.radius_m / M_IN_KM if criteria.radius_m is not None else None,
            min_budget=criteria.min_budget,
            urgencies=list(criteria.urgencies),
            languages=list(criteria.languages),
        )


class JobAlertOut(BaseModel):
    id: UUID
    criteria: JobAlertCriteriaOut
    delivery: AlertDelivery
    is_active: bool = Field(description="Переключатель S18")
    paused_until: datetime | None = Field(description="Пауза из бота: до этого момента молчит")
    week_count: int = Field(description="Сколько заявок подошло за неделю — «8 заявок за неделю»")
    created_at: datetime

    @classmethod
    def of(cls, item: AlertItem) -> JobAlertOut:
        alert = item.alert
        return cls(
            id=alert.id,
            criteria=JobAlertCriteriaOut.of(alert.criteria),
            delivery=alert.delivery,
            is_active=alert.is_active,
            paused_until=alert.paused_until,
            week_count=item.week_count,
            created_at=alert.created_at,
        )


class JobAlertsOut(BaseModel):
    items: list[JobAlertOut] = Field(description="По порядку создания")
    limit: int = Field(description="Сколько подписок можно")

    @classmethod
    def of(cls, items: list[AlertItem]) -> JobAlertsOut:
        return cls(items=[JobAlertOut.of(item) for item in items], limit=MAX_ALERTS)
