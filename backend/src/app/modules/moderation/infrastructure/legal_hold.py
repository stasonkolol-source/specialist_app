"""Legal hold файлов по открытым кейсам (ADR-0016 §6): реализация media.api.LegalHold.

Файл удерживается, пока открыт кейс о нём самом (`entity_type = media`) или кейс, где он —
доказательство (`cases.media_ids`), а с 6.1c — и пока идёт спор, где он доказательство (фасад
deals: кейс спора открывает задача после commit — спор держит файлы и до неё). Читает в
транзакции очистки media (та же сессия).
"""

from collections.abc import Collection

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deals.api import DealsApi
from app.modules.media.api import LegalHold
from app.modules.moderation.domain.cases import OPEN, EntityType
from app.modules.moderation.infrastructure.models import CaseRow
from app.platform.kernel.ids import MediaId


class CasesLegalHold(LegalHold):
    def __init__(self, session: AsyncSession, deals: DealsApi) -> None:
        self._session, self._deals = session, deals

    async def held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        wanted = set(media_ids)
        if not wanted:
            return frozenset()
        ids = list(wanted)
        is_open = CaseRow.status.in_(OPEN)
        subject = select(CaseRow.entity_id.label("media_id")).where(
            is_open, CaseRow.entity_type == EntityType.MEDIA, CaseRow.entity_id.in_(ids)
        )
        evidence = select(func.unnest(CaseRow.media_ids).label("media_id")).where(
            is_open, CaseRow.media_ids.overlap(ids)
        )
        rows = await self._session.execute(union(subject, evidence))
        held = {MediaId(media_id) for (media_id,) in rows if media_id in wanted}
        return frozenset(held | await self._deals.dispute_evidence_held(wanted - held))
