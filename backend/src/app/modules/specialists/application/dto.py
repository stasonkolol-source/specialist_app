"""DTO модуля specialists (ADR-0020 §6)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.media.api import MediaRef
from app.modules.specialists.domain.completeness import Completeness
from app.modules.specialists.domain.portfolio import PortfolioItemId, WorkKind
from app.modules.specialists.domain.profile import (
    Language,
    ProfileId,
    ProfileKind,
    ProfileStatus,
    WorkMode,
)
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileView:
    """Свой профиль в кабинете (S33): статус, поля мастера S32a–c и чего не хватает."""

    id: ProfileId
    kind: ProfileKind
    status: ProfileStatus
    display_name: str
    headline: str | None
    about: str | None
    languages: tuple[Language, ...]
    city_id: CityId
    category_ids: tuple[CategoryId, ...]
    area_ids: tuple[DistrictId, ...]
    travel_radius_km: int | None
    work_modes: tuple[WorkMode, ...]
    listed_in_catalog: bool
    rejection_reason: str | None
    missing: tuple[str, ...]
    """Что заполнить перед отправкой на проверку."""
    available_until: datetime | None
    """«Доступен сегодня до …»; прошедшее время снимает задача reset_availability."""
    avatar_media_id: MediaId | None
    published_at: datetime | None
    version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CabinetView:
    """Свой профиль в кабинете (S33): профиль с тем, чего не хватает для проверки, полнота и
    фото профиля."""

    profile: ProfileView
    completeness: Completeness
    avatar: MediaRef | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkView:
    """Работа портфолио в кабинете S37: файл может ещё обрабатываться (`media.status`)."""

    id: PortfolioItemId
    kind: WorkKind
    caption: str | None
    position: int
    media: MediaRef | None
    """None — файл уже удалён (работу убирают)."""
