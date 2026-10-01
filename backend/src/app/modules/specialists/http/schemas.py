"""Схемы HTTP кабинета исполнителя `/me/profile*` (ARCHITECTURE §8.5)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.domain.profile import (
    MAX_ABOUT,
    MAX_AREAS,
    MAX_CATEGORIES,
    MAX_HEADLINE,
    MAX_NAME,
    Language,
    ProfileKind,
    ProfileStatus,
    WorkMode,
)

INT4_MAX = 2**31 - 1


class ProfileCreateIn(BaseModel):
    kind: ProfileKind
    city_id: int = Field(ge=1, le=INT4_MAX)
    """Город из онбординга (GET /me)."""
    display_name: str | None = Field(default=None, max_length=MAX_NAME)
    """Пусто — имя из Telegram."""


class ProfileUpdateIn(BaseModel):
    """Поля мастера S32b–c и правки S34; не переданное поле не меняется, пустая строка
    очищает «коротко о себе» и «о себе»."""

    kind: ProfileKind | None = None
    """Только у черновика (иначе 409 `profile_state_conflict`); «Подработка → Специалист» у
    проверенного профиля — POST /me/profile/become-pro."""
    display_name: str | None = Field(default=None, max_length=MAX_NAME)
    headline: str | None = Field(default=None, max_length=MAX_HEADLINE)
    about: str | None = Field(default=None, max_length=MAX_ABOUT)
    languages: list[Language] | None = Field(default=None, max_length=len(Language))
    travel_radius_km: Literal[3, 5, 10] | None = None
    work_modes: list[WorkMode] | None = Field(default=None, max_length=len(WorkMode))


class ProfileCategoriesIn(BaseModel):
    category_ids: list[int] = Field(min_length=1, max_length=MAX_CATEGORIES)
    """Первая — основная."""


class ProfileAreasIn(BaseModel):
    district_ids: list[int] = Field(max_length=MAX_AREAS)


class ProfileOut(BaseModel):
    id: UUID
    kind: ProfileKind
    status: ProfileStatus
    display_name: str
    headline: str | None
    about: str | None
    languages: list[Language]
    city_id: int
    category_ids: list[int]
    """Первая — основная."""
    district_ids: list[int]
    travel_radius_km: int | None
    work_modes: list[WorkMode]
    listed_in_catalog: bool
    """Подработка по умолчанию в каталоге не показывается."""
    rejection_reason: str | None
    """Модерация вернула на правки: код причины (тексты — moderation_reason.*)."""
    missing: list[str]
    """Что заполнить перед отправкой на проверку: category_ids, headline, work_modes, area_ids,
    services (позиция прайса у «Специалиста»)."""
    published_at: datetime | None
    version: int

    @classmethod
    def of(cls, view: ProfileView) -> ProfileOut:
        return cls(
            id=view.id,
            kind=view.kind,
            status=view.status,
            display_name=view.display_name,
            headline=view.headline,
            about=view.about,
            languages=list(view.languages),
            city_id=view.city_id,
            category_ids=list(view.category_ids),
            district_ids=list(view.area_ids),
            travel_radius_km=view.travel_radius_km,
            work_modes=list(view.work_modes),
            listed_in_catalog=view.listed_in_catalog,
            rejection_reason=view.rejection_reason,
            missing=list(view.missing),
            published_at=view.published_at,
            version=view.version,
        )
