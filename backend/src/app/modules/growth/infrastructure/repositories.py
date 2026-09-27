"""Репозитории growth (ADR-0020 §5): простая запись без агрегата."""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.growth.domain.attribution import FirstTouch
from app.modules.growth.infrastructure.models import AttributionRow
from app.modules.identity.api import UserNotFoundError
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


class SqlAttributionRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def record_first_touch(self, user_id: UserId, touch: FirstTouch, *, at: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            insert(AttributionRow)
            .values(
                user_id=user_id,
                source=touch.source,
                start_param=touch.start_param,
                referral_code=touch.referral_code,
                entry_point=touch.entry_point,
                first_seen_at=at,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
            .returning(AttributionRow.user_id)
        )
        try:
            inserted = (await self._session.execute(stmt)).scalar_one_or_none()
        except IntegrityError as err:
            raise_domain_error(
                err, {"fk_attributions_user_id_users": lambda: UserNotFoundError(user_id=user_id)}
            )
        return inserted is not None
