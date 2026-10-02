"""Схемы HTTP jobs (ARCHITECTURE §8.5): заявка на входе и на выходе, карточка ленты.

Суммы — в пара (1 RSD = 100 пара), наружу — `MoneyOut`. Точная точка и адрес — только
владельцу (`viewer_role: owner`); гость и исполнитель видят район и смещённую точку (§7.6).
Названия категорий и районов клиент берёт из справочников: в ответе — их id.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.jobs.application.content import JobDraft
from app.modules.jobs.application.feed import JobCard, Photo
from app.modules.jobs.application.use_cases.show_job import JobClient, JobDetails
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
from app.platform.http.money import MoneyOut
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId
from app.platform.kernel.money import Currency, Money

MAX_LANGUAGES = 4
ViewerRole = Literal["owner", "viewer"]


class JobPointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class JobPointOut(BaseModel):
    lat: float
    lon: float


class JobIn(BaseModel):
    title: str = Field(min_length=MIN_TITLE, max_length=MAX_TITLE)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    category_id: int = Field(ge=1, description="Услуга (лист каталога), где включены заявки")
    urgency: Urgency
    budget_type: BudgetType
    budget_min: int | None = Field(default=None, ge=1, le=MAX_BUDGET, description="Пара")
    budget_max: int | None = Field(default=None, ge=1, le=MAX_BUDGET, description="Пара")
    budget_unit: BudgetUnit = BudgetUnit.WORK
    city_id: int = Field(ge=1)
    district_id: int | None = Field(default=None, ge=1)
    point: JobPointIn | None = Field(
        default=None, description="Точная точка: видит только выбранный исполнитель"
    )
    address_private: str | None = Field(
        default=None, max_length=MAX_ADDRESS, description="Подъезд и этаж — тоже только ему"
    )
    preferred_from: datetime | None = None
    preferred_to: datetime | None = None
    languages: list[str] = Field(default_factory=list, max_length=MAX_LANGUAGES)
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
    point_exact: JobPointOut | None = Field(description="Только владельцу")
    address_private: str | None = Field(description="Только владельцу")
    languages: list[str]
    media_ids: list[UUID]
    photos: list[JobPhotoOut] = Field(description="Готовые фото, вариант md (800 px)")
    client: JobClientOut | None = Field(description="Блок клиента; null — аккаунт удалён")
    max_responses: int
    responses_count: int
    extensions_count: int = Field(description="Сколько раз продлевали: не больше трёх")
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
            point_exact=_point(job.point_exact) if owner else None,
            address_private=job.address_private if owner else None,
            languages=list(job.languages),
            media_ids=list(job.media_ids),
            photos=[JobPhotoOut.of(photo) for photo in details.photos],
            client=JobClientOut.of(details.client) if details.client else None,
            max_responses=job.max_responses,
            responses_count=job.responses_count,
            extensions_count=job.extensions_count,
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
