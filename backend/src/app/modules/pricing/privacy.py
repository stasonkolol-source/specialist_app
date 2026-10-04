"""Выгрузка данных pricing (DEVELOPMENT_PLAN 2.12b): позиции прайса профиля пользователя.

Профиль — в specialists: его id даёт фасад, строки прайса читаются здесь же.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.infrastructure.models import ServiceRow
from app.modules.specialists.api import SpecialistsApi
from app.platform.kernel.ids import UserId
from app.platform.privacy.registry import export_section, table_of


async def services(container: AsyncContainer, user_id: UUID) -> Mapping[str, Any]:
    async with container() as request:
        profile = await (await request.get(SpecialistsApi)).profile_of(UserId(user_id))
        if profile is None:
            return {"services": []}
        session = await request.get(AsyncSession)
        rows = await session.execute(
            select(table_of(ServiceRow)).where(ServiceRow.profile_id == profile.id)
        )
        return {"services": [dict(row._mapping) for row in rows]}


export_section("pricing", supplement=services)
