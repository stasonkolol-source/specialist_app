"""Фикстуры growth: use case атрибуции на сессии теста (откат в конце)."""

from dataclasses import dataclass

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.growth.application.use_cases.record_attribution import RecordAttribution
from app.modules.growth.infrastructure.repositories import SqlAttributionRepository
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.ids import UserId


@dataclass
class Growth:
    session: AsyncSession
    uow: SqlAlchemyUnitOfWork
    record: RecordAttribution

    async def attribution(self, user_id: UserId) -> dict[str, object] | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT source, start_param, referral_code, entry_point, first_seen_at"
                    " FROM growth.attributions WHERE user_id = :user_id"
                ),
                {"user_id": user_id},
            )
        ).one_or_none()
        return dict(row._mapping) if row is not None else None


@pytest.fixture
def growth(db_session: AsyncSession, procrastinate_app: procrastinate.App) -> Growth:
    uow = make_uow(db_session, procrastinate_app)
    return Growth(
        session=db_session,
        uow=uow,
        record=RecordAttribution(uow, SqlAttributionRepository(db_session, uow)),
    )
