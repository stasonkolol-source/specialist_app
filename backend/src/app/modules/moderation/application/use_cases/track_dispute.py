"""Спор по сделке в очереди модерации (подписчики deals; DEVELOPMENT_PLAN 6.1c, ARCHITECTURE
§14.4): кейс `dispute` живёт вместе со спором.

- открыт (DealDisputed) — кейс в очереди P1 (угрозы — P0) о второй стороне: вид, сделка, кто
  открыл, срок ответа, фото открывшего (legal hold, пока кейс открыт); срок P1 — после 48 ч на
  ответ: раньше модератору решать нечего;
- ответ второй стороны (DisputeAnswered) — повод «answered» и её фото, срок ближе;
- 48 ч без ответа (DisputeUnanswered) — повод «no_response»: пометка «нет ответа»;
- отозван (DisputeWithdrawn) — кейс закрыт без решения.

Задачи могут прийти в любом порядке и повториться: спор читается из deals заново, кейс
открывается тем шагом, который пришёл первым, пометка не дублируется.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.deals.api import DealsApi, DisputeSummary
from app.modules.moderation.application.ports import CaseRepository, ModerationPolicy
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import dispute_queue
from app.modules.moderation.domain.sla import dispute_due_at
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


class DisputeStep(StrEnum):
    OPENED = "opened"
    ANSWERED = "answered"
    UNANSWERED = "no_response"
    WITHDRAWN = "withdrawn"


NOTED: Final = frozenset({DisputeStep.ANSWERED, DisputeStep.UNANSWERED})
"""Шаги, которые дописываются в кейс поводом с `details.event`."""
WITHDRAWN_STATUS: Final = "withdrawn"


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackDisputeCommand:
    dispute_id: UUID
    """id спора в deals."""
    step: DisputeStep


class TrackDispute:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        deals: DealsApi,
        policy: ModerationPolicy,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._cases, self._deals = uow, cases, deals
        self._policy, self._audit, self._clock = policy, audit, clock

    async def __call__(self, cmd: TrackDisputeCommand) -> None:
        dispute = await self._deals.dispute(cmd.dispute_id)
        if dispute is None:
            return
        policy_version = await self._policy.version()
        await retry_on_conflict(lambda: self._track(dispute, cmd.step, policy_version))

    async def _track(self, dispute: DisputeSummary, step: DisputeStep, policy: str) -> None:
        now = self._clock.now()
        async with self._uow:
            case = await self._cases.open_for_entity(EntityType.DISPUTE, dispute.id)
            if dispute.status == WITHDRAWN_STATUS:
                if case is not None:
                    case.withdraw(policy_version=policy, now=now)
                    await self._cases.save(case)
                    await self._audit.record(
                        AuditEntry(
                            action="moderation.case.withdrawn",
                            actor_kind=ActorKind.USER,
                            actor_id=dispute.opened_by,
                            entity_type="moderation.case",
                            entity_id=case.id,
                        )
                    )
                return
            if not dispute.is_active:
                return  # решён: кейс закрыл ResolveDispute
            if case is None:
                case = await self._open(dispute)
            if step in NOTED and not case.has_event(step.value) and _happened(dispute, step):
                case.add_trigger(
                    queue=case.queue,
                    trigger=CaseTrigger.DISPUTE,
                    now=now,
                    details={"event": step.value},
                    media_ids=dispute.response_media_ids if step is DisputeStep.ANSWERED else (),
                )
                await self._cases.save(case)

    async def _open(self, dispute: DisputeSummary) -> Case:
        """Кейс — с момента открытия спора: по нему считается SLA очереди."""
        deal = await self._deals.deal_brief(dispute.deal_id)
        queue = dispute_queue(dispute.kind)
        details: dict[str, object] = {
            "event": DisputeStep.OPENED.value,
            "deal_id": str(dispute.deal_id),
            "kind": dispute.kind,
            "opened_by": str(dispute.opened_by),
            "respond_by": dispute.respond_by.isoformat(),
        }
        if deal is not None:
            details["title"] = deal.title
        case = Case.open(
            queue=queue,
            entity_type=EntityType.DISPUTE,
            entity_id=dispute.id,
            subject_id=UserId(dispute.respondent_id),
            trigger=CaseTrigger.DISPUTE,
            now=dispute.created_at,
            details=details,
            media_ids=dispute.media_ids,
            due=dispute_due_at(queue, dispute.created_at, dispute.respond_by),
        )
        await self._cases.add(case)  # параллельный шаг успел открыть — CaseAlreadyOpenError, повтор
        await self._audit.record(
            AuditEntry(
                action="moderation.case.opened",
                actor_kind=ActorKind.SYSTEM,
                entity_type="moderation.case",
                entity_id=case.id,
                changes={"queue": case.queue.value, "trigger": case.trigger.value},
            )
        )
        return case


def _happened(dispute: DisputeSummary, step: DisputeStep) -> bool:
    """Шаг виден в самом споре: задачу ответа не путаем с повтором открытия."""
    if step is DisputeStep.ANSWERED:
        return dispute.responded_at is not None
    return dispute.unanswered_at is not None
