"""Открыть спор (POST /deals/{id}/dispute, S52; DEVELOPMENT_PLAN 6.1c): сторона идущей сделки —
что случилось, описание и фото-доказательства. Сделка — `disputed`; DealDisputed — кейс
модерации P1 (угрозы — P0), второй стороне `dispute.opened` и 48 ч на ответ, аналитика.

Фото — свои файлы назначения `dispute` (приватный бакет): чужой или удалённый — 404,
другое назначение или отказ обработки — 409. Проверка — до транзакции (чтение media).

Лимит — пять открытых споров в сутки: квота берётся последней, когда спор прошёл все проверки,
так что отказы 404 и 409 её не тратят (MU-9); сверх — 429, спор не создан.
"""

from dataclasses import dataclass

from app.modules.deals.application.ports import (
    DealRepository,
    DisputeQuota,
    DisputeRepository,
)
from app.modules.deals.domain.dispute import Dispute, DisputeId, DisputeKind
from app.modules.media.api import MediaApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, MediaId, UserId, new_id

EVIDENCE_PURPOSE = "dispute"


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenDisputeCommand:
    actor_id: UserId
    deal_id: DealId
    kind: DisputeKind
    description: str
    media_ids: tuple[MediaId, ...] = ()


class OpenDispute:
    def __init__(
        self,
        uow: UnitOfWork,
        deals: DealRepository,
        disputes: DisputeRepository,
        quota: DisputeQuota,
        media: MediaApi,
        clock: Clock,
    ) -> None:
        self._uow, self._deals, self._disputes = uow, deals, disputes
        self._quota, self._media, self._clock = quota, media, clock

    async def __call__(self, cmd: OpenDisputeCommand) -> DisputeId:
        await check_evidence(self._media, cmd.actor_id, cmd.media_ids)
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            dispute = Dispute.open(
                dispute_id=DisputeId(new_id()),
                deal=deal,
                actor_id=cmd.actor_id,
                kind=cmd.kind,
                description=cmd.description,
                media_ids=cmd.media_ids,
                now=self._clock.now(),
            )
            await self._disputes.add(dispute)
            await self._deals.save(deal)
            await self._quota.take(cmd.actor_id)  # сверх лимита — 429 и откат транзакции
        return dispute.id


async def check_evidence(media: MediaApi, owner_id: UserId, media_ids: tuple[MediaId, ...]) -> None:
    """Фото — свои, назначения `dispute`, загружены (обработка может ещё идти)."""
    for media_id in dict.fromkeys(media_ids):
        await media.owned(owner_id, media_id, purpose=EVIDENCE_PURPOSE)
