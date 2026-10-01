"""Репозиторий профилей (ADR-0020 §5): профиль с категориями и районами — один агрегат."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.specialists.domain.profile import Language, Profile, ProfileId, WorkMode
from app.modules.specialists.errors import ProfileExistsError, ProfileNotFoundError
from app.modules.specialists.infrastructure.models import (
    ProfileCategoryRow,
    ProfileRow,
    ServiceAreaRow,
)
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId


class SqlProfileRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def of_user(self, user_id: UserId) -> Profile | None:
        """Профиль пользователя под блокировкой строки (кабинет: одна правка за раз)."""
        return await self._load(ProfileRow.user_id == user_id)

    async def get_for_update(self, profile_id: ProfileId) -> Profile:
        profile = await self._load(ProfileRow.id == profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id=profile_id)
        return profile

    async def add(self, profile: Profile) -> None:
        self._uow.require_active()
        row = ProfileRow(id=profile.id, version=profile.version, created_at=profile.created_at)
        _apply(profile, row)
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, {"uq_profiles_user_id_alive": ProfileExistsError})
        await self._replace_children(profile)
        self._uow.track(profile)

    async def save(self, profile: Profile) -> None:
        self._uow.require_active()
        row = await self._session.get(ProfileRow, profile.id)
        if row is None:
            raise ProfileNotFoundError(profile_id=profile.id)
        check_loaded_version(entity="profile", loaded=row.version, expected=profile.version)
        _apply(profile, row)
        row.version = profile.version + 1
        await self._session.flush()
        await self._replace_children(profile)
        profile.mark_persisted(version=row.version)
        self._uow.track(profile)

    async def expired_availability(self, now: datetime, *, limit: int) -> list[ProfileId]:
        self._uow.require_active()
        stmt = (
            select(ProfileRow.id)
            .where(ProfileRow.available_until <= now, ProfileRow.deleted_at.is_(None))
            .order_by(ProfileRow.available_until)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [ProfileId(value) for value in (await self._session.scalars(stmt)).all()]

    async def _load(self, condition: object) -> Profile | None:
        self._uow.require_active()
        stmt = (
            select(ProfileRow)
            .where(condition, ProfileRow.deleted_at.is_(None))  # type: ignore[arg-type]
            .with_for_update(of=ProfileRow)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        categories = (
            await self._session.execute(
                select(ProfileCategoryRow.category_id)
                .where(ProfileCategoryRow.profile_id == row.id)
                .order_by(ProfileCategoryRow.position)
            )
        ).scalars()
        areas = (
            await self._session.execute(
                select(ServiceAreaRow.district_id)
                .where(ServiceAreaRow.profile_id == row.id)
                .order_by(ServiceAreaRow.position)
            )
        ).scalars()
        profile = _to_domain(
            row,
            tuple(CategoryId(c) for c in categories),
            tuple(DistrictId(d) for d in areas),
        )
        self._uow.track(profile)
        return profile

    async def _replace_children(self, profile: Profile) -> None:
        await self._session.execute(
            delete(ProfileCategoryRow).where(ProfileCategoryRow.profile_id == profile.id)
        )
        await self._session.execute(
            delete(ServiceAreaRow).where(ServiceAreaRow.profile_id == profile.id)
        )
        self._session.add_all(
            ProfileCategoryRow(
                profile_id=profile.id,
                category_id=category_id,
                is_primary=index == 0,
                position=index,
            )
            for index, category_id in enumerate(profile.category_ids)
        )
        self._session.add_all(
            ServiceAreaRow(profile_id=profile.id, district_id=district_id, position=index)
            for index, district_id in enumerate(profile.area_ids)
        )
        await self._session.flush()


def _to_domain(
    row: ProfileRow, categories: tuple[CategoryId, ...], areas: tuple[DistrictId, ...]
) -> Profile:
    return Profile(
        id=ProfileId(row.id),
        user_id=UserId(row.user_id),
        kind=row.kind,
        status=row.status,
        display_name=row.display_name,
        city_id=CityId(row.city_id),
        created_at=row.created_at,
        headline=row.headline,
        about=row.about,
        languages=tuple(Language(v) for v in row.languages),
        category_ids=categories,
        area_ids=areas,
        base_point=row.base_point,
        base_point_public=row.base_point_public,
        travel_radius_km=row.travel_radius_km,
        work_modes=tuple(WorkMode(v) for v in row.work_modes),
        listed_in_catalog=row.listed_in_catalog,
        is_founding=row.is_founding,
        available_until=row.available_until,
        vacation_until=row.vacation_until,
        rejection_reason=row.rejection_reason,
        submitted_at=row.submitted_at,
        published_at=row.published_at,
        reviewed_kind=row.reviewed_kind,
        version=row.version,
    )


def _apply(profile: Profile, row: ProfileRow) -> None:
    row.user_id = profile.user_id
    row.kind = profile.kind
    row.status = profile.status
    row.display_name = profile.display_name
    row.headline = profile.headline
    row.about = profile.about
    row.languages = [language.value for language in profile.languages]
    row.city_id = profile.city_id
    row.district_id = profile.area_ids[0] if profile.area_ids else None
    row.base_point = profile.base_point
    row.base_point_public = profile.base_point_public
    row.travel_radius_km = profile.travel_radius_km
    row.work_modes = [mode.value for mode in profile.work_modes]
    row.listed_in_catalog = profile.listed_in_catalog
    row.is_founding = profile.is_founding
    row.available_until = profile.available_until
    row.vacation_until = profile.vacation_until
    row.rejection_reason = profile.rejection_reason
    row.reviewed_kind = profile.reviewed_kind
    row.submitted_at = profile.submitted_at
    row.published_at = profile.published_at
