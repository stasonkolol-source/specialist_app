"""Репозитории growth (ADR-0020 §5): простая запись без агрегата."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.growth.domain.attribution import FirstTouch
from app.modules.growth.domain.share import new_referral_code
from app.modules.growth.infrastructure.models import AttributionRow, ReferralCodeRow
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

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(AttributionRow).where(AttributionRow.user_id == user_id))


ATTEMPTS = 3
"""Новый код совпал с чужим (62^8 вариантов) — взять другой; три раза подряд не бывает."""


class SqlReferralCodes:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def code_of(self, owner_id: UserId) -> str:
        self._uow.require_active()
        for _ in range(ATTEMPTS):
            existing = await self._existing(owner_id)
            if existing is not None:
                return existing
            # гонка двух «Поделиться» одного человека: вставит один, второй прочитает его код
            stmt = (
                insert(ReferralCodeRow)
                .values(code=new_referral_code(), owner_id=owner_id)
                .on_conflict_do_nothing()
                .returning(ReferralCodeRow.code)
            )
            try:
                inserted = (await self._session.execute(stmt)).scalar_one_or_none()
            except IntegrityError as err:
                raise_domain_error(
                    err,
                    {
                        "fk_referral_codes_owner_id_users": lambda: UserNotFoundError(
                            user_id=owner_id
                        )
                    },
                )
            if inserted is not None:
                return inserted
        raise RuntimeError("referral code: no free code after retries")

    async def _existing(self, owner_id: UserId) -> str | None:
        stmt = select(ReferralCodeRow.code).where(ReferralCodeRow.owner_id == owner_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def forget(self, owner_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(
            delete(ReferralCodeRow).where(ReferralCodeRow.owner_id == owner_id)
        )
