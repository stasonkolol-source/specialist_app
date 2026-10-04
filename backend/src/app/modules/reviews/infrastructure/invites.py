"""Ссылки-приглашения на «отзыв до платформы» в `reviews.review_invites` (DEVELOPMENT_PLAN 7.6а).

Лимит пяти мест считается в приложении: новые ссылки профиля создаются под его advisory lock,
поэтому две одновременные не займут шестое место. Ссылку, по которой пишут отзыв, держит
блокировка строки: второй отзыв по ней не пройдёт.
"""

from uuid import UUID

from sqlalchemy import RowMapping, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reviews.application.dto import InviteListing
from app.modules.reviews.domain.invite import ReviewInvite
from app.modules.reviews.domain.review import ReviewStatus
from app.modules.reviews.infrastructure.models import ReviewInviteRow, ReviewRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId

_I = ReviewInviteRow.__table__.c
_R = ReviewRow.__table__.c


class SqlReviewInvites(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def lock(self, profile_id: UUID) -> None:
        self._uow.require_active()
        key = func.hashtextextended(f"reviews.invites:{profile_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def of_profile(self, profile_id: UUID) -> list[ReviewInvite]:
        rows = await self._fetch(
            select(ReviewInviteRow.__table__).where(_I.profile_id == profile_id)
        )
        return [_to_domain(row) for row in rows]

    async def add(self, invite: ReviewInvite) -> None:
        self._uow.require_active()
        self._session.add(
            ReviewInviteRow(
                token=invite.token,
                profile_id=invite.profile_id,
                client_name=invite.client_name,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
            )
        )
        await self._session.flush()

    async def find_for_update(self, token: UUID) -> ReviewInvite | None:
        self._uow.require_active()
        stmt = select(ReviewInviteRow.__table__).where(_I.token == token).with_for_update()
        row = (await self._session.execute(stmt)).mappings().one_or_none()
        return _to_domain(row) if row is not None else None

    async def find(self, token: UUID) -> ReviewInvite | None:
        row = await self._fetch_one(select(ReviewInviteRow.__table__).where(_I.token == token))
        return _to_domain(row) if row is not None else None

    async def mark_used(self, invite: ReviewInvite) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(ReviewInviteRow)
            .where(ReviewInviteRow.token == invite.token)
            .values(used_by=invite.used_by, used_at=invite.used_at, review_id=invite.review_id)
        )

    async def remove(self, token: UUID) -> None:
        self._uow.require_active()
        await self._session.execute(delete(ReviewInviteRow).where(ReviewInviteRow.token == token))

    async def listing(self, profile_id: UUID) -> list[InviteListing]:
        rows = await self._fetch(
            select(
                _I.token,
                _I.client_name,
                _I.created_at,
                _I.expires_at,
                _I.used_by,
                _I.used_at,
                _I.review_id,
                _R.status,
                _R.rating,
                _R.published_at,
                _R.deleted_at,
            )
            .select_from(ReviewInviteRow.__table__.outerjoin(ReviewRow.__table__))
            .where(_I.profile_id == profile_id)
            .order_by(_I.created_at.desc(), _I.token.desc())
        )
        return [
            InviteListing(
                token=row["token"],
                client_name=row["client_name"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                used_by=UserId(row["used_by"]) if row["used_by"] is not None else None,
                used_at=row["used_at"],
                review_id=row["review_id"],
                review_status=(
                    ReviewStatus.REMOVED.value if row["deleted_at"] is not None else row["status"]
                ),
                rating=row["rating"],
                published_at=row["published_at"],
            )
            for row in rows
        ]


def _to_domain(row: RowMapping) -> ReviewInvite:
    return ReviewInvite(
        token=row["token"],
        profile_id=row["profile_id"],
        client_name=row["client_name"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_by=UserId(row["used_by"]) if row["used_by"] is not None else None,
        used_at=row["used_at"],
        review_id=row["review_id"],
    )
