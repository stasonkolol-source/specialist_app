"""Legal hold сроков хранения (ARCHITECTURE §7.10, 2.12b): реализация platform RetentionHold.

Заявку, отклик и сообщение правило хранения не удаляет, пока о них открыт кейс модерации, а
переписку по сделке — пока идёт спор (фасад deals). Читает в транзакции правила.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deals.api import DealsApi
from app.modules.moderation.domain.cases import OPEN, EntityType
from app.modules.moderation.infrastructure.models import CaseRow
from app.platform.kernel.ids import DealId
from app.platform.privacy.port import HoldKind, RetentionHold

_CASE_ENTITY = {
    HoldKind.JOB: EntityType.JOB,
    HoldKind.RESPONSE: EntityType.RESPONSE,
    HoldKind.MESSAGE: EntityType.MESSAGE,
}


class CasesRetentionHold(RetentionHold):
    def __init__(self, session: AsyncSession, deals: DealsApi) -> None:
        self._session, self._deals = session, deals

    async def held(self, kind: HoldKind, ids: Collection[UUID]) -> frozenset[UUID]:
        wanted = list(set(ids))
        if not wanted:
            return frozenset()
        if kind is HoldKind.DEAL:
            return frozenset(await self._deals.disputed_deals([DealId(i) for i in wanted]))
        stmt = (
            select(CaseRow.entity_id)
            .where(
                CaseRow.status.in_(OPEN),
                CaseRow.entity_type == _CASE_ENTITY[kind],
                CaseRow.entity_id.in_(wanted),
            )
            .distinct()
        )
        return frozenset((await self._session.scalars(stmt)).all())
