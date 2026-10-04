"""Выгрузка данных specialists (DEVELOPMENT_PLAN 2.12b): профиль, категории, районы, портфолио.

Правила хранения нет: профиль живёт до удаления аккаунта (матрица §7.10), отклонённый
модерацией профиль — черновик владельца, он его правит. Отклонённые работы портфолио появятся
с модерацией изображений (6.7) — тогда и правило «6 месяцев».
"""

from uuid import UUID

from sqlalchemy import ColumnElement, Select, select

from app.modules.specialists.infrastructure.models import (
    PortfolioItemRow,
    PortfolioMediaRow,
    ProfileCategoryRow,
    ProfileRow,
    ServiceAreaRow,
)
from app.platform.privacy.registry import ExportTable, export_section


def _profile_of(user_id: UUID) -> ColumnElement[bool]:
    return ProfileRow.user_id == user_id


def _profiles(user_id: UUID) -> Select[UUID]:
    return select(ProfileRow.id).where(_profile_of(user_id))


def _items(user_id: UUID) -> Select[UUID]:
    return select(PortfolioItemRow.id).where(PortfolioItemRow.profile_id.in_(_profiles(user_id)))


export_section(
    "specialists",
    ExportTable(ProfileRow, _profile_of),
    ExportTable(
        ProfileCategoryRow, lambda user: ProfileCategoryRow.profile_id.in_(_profiles(user))
    ),
    ExportTable(ServiceAreaRow, lambda user: ServiceAreaRow.profile_id.in_(_profiles(user))),
    ExportTable(PortfolioItemRow, lambda user: PortfolioItemRow.profile_id.in_(_profiles(user))),
    ExportTable(PortfolioMediaRow, lambda user: PortfolioMediaRow.item_id.in_(_items(user))),
)
