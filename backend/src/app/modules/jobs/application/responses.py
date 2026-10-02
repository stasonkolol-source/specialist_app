"""Отклики для чтения (DEVELOPMENT_PLAN 5.4): «Мои отклики» исполнителя (S17) и отклики на заявку
для её владельца (S23). Группы S17 — чипы «Активные / Выбран / Не выбран / Архив»."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.jobs.domain.job import BudgetType, BudgetUnit, JobId, JobStatus, Urgency
from app.modules.jobs.domain.response import (
    ACTIVE,
    Offer,
    ResponseId,
    ResponseStatus,
    Review,
)
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId


class ResponseGroup(StrEnum):
    ACTIVE = "active"
    ACCEPTED = "accepted"
    NOT_SELECTED = "not_selected"
    ARCHIVE = "archive"


GROUP_STATUSES: Final[dict[ResponseGroup, frozenset[ResponseStatus]]] = {
    ResponseGroup.ACTIVE: ACTIVE,
    ResponseGroup.ACCEPTED: frozenset({ResponseStatus.ACCEPTED}),
    ResponseGroup.NOT_SELECTED: frozenset({ResponseStatus.NOT_SELECTED, ResponseStatus.DECLINED}),
    ResponseGroup.ARCHIVE: frozenset({ResponseStatus.WITHDRAWN}),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseJob:
    """Заявка в карточке «Мои отклики»: что, где, когда, бюджет и места."""

    id: JobId
    title: str
    status: JobStatus
    category_id: CategoryId
    city_id: CityId
    district_id: DistrictId | None
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: int | None
    budget_max: int | None
    budget_unit: BudgetUnit
    responses_count: int
    max_responses: int
    published_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MyResponse:
    id: ResponseId
    status: ResponseStatus
    review: Review
    offer: Offer
    is_first: bool
    """Первый отклик на заявку — «Первый отклик» на S17 и «Откликнулся первым» на S23."""
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    job: ResponseJob


@dataclass(frozen=True, slots=True, kw_only=True)
class TodayQuota:
    """«Сегодня откликов: 3 из 50 — лимит по уровню доверия» (S17)."""

    used: int
    limit: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerResponse:
    """Отклик на заявку для её владельца: только прошедшие проверку."""

    id: ResponseId
    performer_id: UserId
    profile_id: UUID | None
    status: ResponseStatus
    offer: Offer
    is_first: bool
    created_at: datetime
    updated_at: datetime
