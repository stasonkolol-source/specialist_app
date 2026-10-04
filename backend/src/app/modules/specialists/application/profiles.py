"""Общее для команд кабинета: свой профиль, проверки справочников, запрос модерации."""

from collections.abc import Iterable
from datetime import datetime

from app.modules.catalog.api import CatalogApi, RiskLevel
from app.modules.geo.api import GeoApi
from app.modules.specialists.api import PriceList
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.domain.portfolio import PortfolioItem, WorkStatus
from app.modules.specialists.domain.profile import Profile, ProfileKind, ProfileStatus
from app.modules.specialists.errors import (
    CategoryNotAllowedError,
    DistrictNotAllowedError,
    ProfileIncompleteError,
    ProfileNotFoundError,
)
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId

PROFILE = "profile"
"""Тип объекта в модерации (`moderation.cases.entity_type`)."""
PORTFOLIO_WORK = "portfolio"
"""Тип работы портфолио в модерации (`moderation.cases.entity_type`, план 6.7)."""


async def own_profile(
    profiles: ProfileRepository, user_id: UserId, expected_version: int | None = None
) -> Profile:
    profile = await profiles.of_user(user_id)
    if profile is None:
        raise ProfileNotFoundError(user_id=user_id)
    profile.ensure_version(expected_version)
    return profile


def request_review(uow: UnitOfWork, profile: Profile, *, edit: bool, now: datetime) -> None:
    """Объект ждёт проверки (§14.1): новый — до публикации, правка — пост-модерация."""
    uow.add_event(
        ModerationRequested(
            entity_type=PROFILE,
            entity_id=profile.id,
            author_id=profile.user_id,
            edit=edit,
            occurred_at=now,
        )
    )


def request_work_review(
    uow: UnitOfWork, item: PortfolioItem, author_id: UserId, *, now: datetime
) -> None:
    """Работа ждёт проверки (план 6.7): новая — до публикации (подпись и фото), правка подписи
    опубликованной — пост-модерация. Скрытую модератором не проверяем: её не видно."""
    if item.status is WorkStatus.REJECTED:
        return
    uow.add_event(
        ModerationRequested(
            entity_type=PORTFOLIO_WORK,
            entity_id=item.id,
            author_id=author_id,
            edit=item.status is WorkStatus.PUBLISHED,
            occurred_at=now,
        )
    )


def needs_post_moderation(profile: Profile, changed: Iterable[str]) -> bool:
    """Текст опубликованного (или скрытого) профиля изменился — проверить после публикации."""
    text_changed = any(name in {"display_name", "headline", "about"} for name in changed)
    return text_changed and profile.status in (ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN)


async def allowed_categories(catalog: CatalogApi, ids: Iterable[CategoryId]) -> list[CategoryId]:
    wanted = list(dict.fromkeys(ids))
    found = {summary.id: summary for summary in await catalog.categories(wanted)}
    for category_id in wanted:
        summary = found.get(category_id)
        if summary is None or not summary.is_active or summary.risk_level is RiskLevel.FORBIDDEN:
            raise CategoryNotAllowedError(category_id=category_id)
    return wanted


async def allowed_areas(
    geo: GeoApi, city_id: CityId, ids: Iterable[DistrictId]
) -> tuple[list[DistrictId], GeoPoint | None]:
    """Районы города профиля; база — центр первого (точного адреса мастер S32c не спрашивает)."""
    wanted = list(dict.fromkeys(ids))
    base = None
    for index, district_id in enumerate(wanted):
        district = await geo.district(district_id)
        if district is None or district.city_id != city_id:
            raise DistrictNotAllowedError(district_id=district_id)
        if index == 0:
            base = district.center
    return wanted, base


async def ensure_price_list(prices: PriceList, profile: Profile) -> None:
    """«Специалиста» без позиции прайса на проверку не отправить (2.8b): 409 со списком."""
    if profile.kind is ProfileKind.PRO and not await prices.has_items(profile.id):
        raise ProfileIncompleteError(missing=[*profile.missing(), "services"])
