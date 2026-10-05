"""Заявка для чтения (экраны S15, S22, S23): всё, что хранит строка; что показать — решает
HTTP по политике видимости (точка и адрес — только владельцу)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.jobs.domain.job import (
    BudgetType,
    BudgetUnit,
    CloseReason,
    JobId,
    JobStatus,
    Urgency,
    Visibility,
)
from app.modules.jobs.domain.response import ResponseId, ResponseReview, ResponseStatus
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DealId, DistrictId, MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobView:
    id: JobId
    client_id: UserId
    status: JobStatus
    visibility: Visibility
    title: str
    description: str
    content_lang: str
    category_id: CategoryId
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: int | None
    budget_max: int | None
    budget_unit: BudgetUnit
    city_id: CityId
    district_id: DistrictId | None
    point_exact: GeoPoint | None
    point_public: GeoPoint | None
    address_private: str | None
    languages: tuple[str, ...]
    media_ids: tuple[MediaId, ...]
    max_responses: int
    responses_count: int
    extensions_count: int
    views_count: int
    """Сколько разных людей открывали заявку (не чаще раза в сутки каждый, 5.6)."""
    notified_count: int
    """Скольким подписчикам заявка подошла — сразу или подборкой (5.7)."""
    responses_seen_at: datetime | None
    """Клиент последний раз открывал отклики (S23): позже прошедшие проверку — «новые»."""
    moderation_note: str | None
    version: int
    """Редакция содержимого (`Job.revision`): ETag и If-Match правки, а не версия строки."""
    created_at: datetime
    published_at: datetime | None
    expires_at: datetime | None
    closed_at: datetime | None
    close_reason: CloseReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MyResponseRef:
    """Свой отклик исполнителя на заявку — MainButton S15: «Вы откликнулись» (5.5)."""

    id: ResponseId
    status: ResponseStatus
    review: ResponseReview


@dataclass(frozen=True, slots=True, kw_only=True)
class DealResponse:
    """Отклик, по которому сделка (S26, 6.2): кто, когда и «когда смогу»."""

    id: ResponseId
    job_id: JobId
    performer_id: UserId
    status: ResponseStatus
    created_at: datetime
    availability_note: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedResponse:
    """Отклик выбран (S25, 6.1a): заявка и созданная сделка — экран сделки S26."""

    job_id: JobId
    deal_id: DealId
