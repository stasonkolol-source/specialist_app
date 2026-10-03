"""Спор глазами модератора (`cli dispute-show`, позже карточка в чате модераторов 2.5b;
DEVELOPMENT_PLAN 6.1c): что случилось, ответ, сроки и фото-доказательства обеих сторон —
presigned GET приватного бакета на 5 минут. Каждый просмотр доказательств персоналом — запись
в audit_log (ADR-0016 §6): кто, когда и какие файлы. Роль проверяет точка входа.
"""

from dataclasses import dataclass

from app.modules.deals.api import DealsApi
from app.modules.media.api import MediaApi
from app.modules.moderation.application.dto import DisputeDossier
from app.modules.moderation.application.ports import CaseRepository
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.errors import CaseKindError, CaseNotFoundError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectDisputeCommand:
    case_id: CaseId
    moderator_id: UserId


class InspectDispute:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        deals: DealsApi,
        media: MediaApi,
        audit: AuditLog,
    ) -> None:
        self._uow, self._cases, self._deals = uow, cases, deals
        self._media, self._audit = media, audit

    async def __call__(self, cmd: InspectDisputeCommand) -> DisputeDossier:
        async with self._uow:  # просмотр и запись о нём — вместе
            case = await self._cases.get_for_update(cmd.case_id)
            if case.entity_type is not EntityType.DISPUTE:
                raise CaseKindError(entity_type=case.entity_type.value)
            dispute = await self._deals.dispute(case.entity_id)
            if dispute is None:
                raise CaseNotFoundError(case_id=cmd.case_id)
            deal = await self._deals.deal_brief(dispute.deal_id)
            media_ids = [*dispute.media_ids, *dispute.response_media_ids]
            photos = await self._media.refs(media_ids) if media_ids else {}
            await self._audit.record(
                AuditEntry(
                    action="moderation.dispute.evidence_viewed",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.moderator_id,
                    entity_type="deals.dispute",
                    entity_id=dispute.id,
                    changes={
                        "case_id": str(case.id),
                        "media_ids": [str(media_id) for media_id in photos],
                    },
                )
            )
        return DisputeDossier(
            case_id=case.id,
            case_status=case.status,
            queue=case.queue,
            due_at=case.due_at,
            dispute=dispute,
            deal=deal,
            photos=photos,
        )
