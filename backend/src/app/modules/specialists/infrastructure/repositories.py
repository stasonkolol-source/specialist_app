"""Репозиторий профилей (ADR-0020 §5): профиль с категориями и районами — один агрегат."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.specialists.domain.profile import (
    Language,
    Profile,
    ProfileId,
    ProfileStatus,
    WorkMode,
)
from app.modules.specialists.errors import ProfileExistsError, ProfileNotFoundError
from app.modules.specialists.infrastructure.models import (
    ProfileCategoryRow,
    ProfileRow,
    ServiceAreaRow,
)
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId


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

    async def stale(
        self, *, updated_before: datetime, reminded_before: datetime, now: datetime, limit: int
    ) -> list[tuple[ProfileId, UserId]]:
        self._uow.require_active()
        p = ProfileRow.__table__.c
        stmt = (
            select(p.id, p.user_id)
            .where(
                p.status == ProfileStatus.PUBLISHED,
                p.deleted_at.is_(None),
                p.updated_at < updated_before,
                or_(p.available_until.is_(None), p.available_until <= now),
                or_(p.vacation_until.is_(None), p.vacation_until < now.date()),
                or_(p.stale_reminded_at.is_(None), p.stale_reminded_at < reminded_before),
            )
            .order_by(p.updated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(ProfileId(row.id), UserId(row.user_id)) for row in rows]

    async def mark_reminded(self, profile_ids: Collection[ProfileId], at: datetime) -> None:
        self._uow.require_active()
        if not profile_ids:
            return
        p = ProfileRow.__table__.c
        await self._session.execute(
            update(ProfileRow)
            .where(p.id.in_(list(profile_ids)))
            # updated_at — как было: по нему решается, давно ли профиль не обновлялся
            .values(stale_reminded_at=at, updated_at=p.updated_at)
            .execution_options(synchronize_session=False)
        )

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
        avatar_media_id=MediaId(row.avatar_media_id) if row.avatar_media_id else None,
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
    row.avatar_media_id = profile.avatar_media_id
    row.submitted_at = profile.submitted_at
    row.published_at = profile.published_at
    row.deleted_at = profile.deleted_at
    if profile.deleted_at is not None:
        # колонки вне домена удалённому профилю тоже не нужны: контакты, адрес страницы, стаж
        row.contacts = {}
        row.slug = None
        row.experience_since = None
