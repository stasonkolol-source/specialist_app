"""Legal hold удаления аккаунта (ARCHITECTURE §7.10): реализация identity.api.DeletionHold.

Удаление ждёт, пока открыт кейс о пользователе (`subject_id`): «жалобы удалим после их
решения» (S45). Споры добавит 6.1c. Читает в транзакции identity.process_deletions.
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import DeletionHold
from app.modules.moderation.domain.cases import OPEN
from app.modules.moderation.infrastructure.models import CaseRow
from app.platform.kernel.ids import UserId


class CasesDeletionHold(DeletionHold):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def held(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        wanted = list(set(user_ids))
        if not wanted:
            return frozenset()
        stmt = (
            select(CaseRow.subject_id)
            .where(CaseRow.status.in_(OPEN), CaseRow.subject_id.in_(wanted))
            .distinct()
        )
        return frozenset(UserId(user_id) for user_id in (await self._session.scalars(stmt)).all())
