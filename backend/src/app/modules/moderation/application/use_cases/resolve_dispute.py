"""Решение модератора по спору (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §14.4, ADR-0016 §4): одной
транзакцией — исход сделки через фасад deals (moderation выше deals по DAG), решение по кейсу и,
если нужно, санкция второй стороне (о ней спор) по лестнице через фасад identity.

- `completed` — работа выполнена: сделка завершена (заявка завершена, клиенту — отзыв);
- `cancelled` — сделка отменена модератором: заявка снова открыта.
Сторонам — `dispute.resolved` с причиной (DisputeResolved → уведомления): statement of reasons.
Санкция — кейс `rejected` (нарушение второй стороны): ей ещё и `moderation.decision`, а санкция с
ограничением — `account.restricted`. Без санкции — кейс `approved`.

Роль модератора проверяет точка входа (`cli dispute-resolve`, позже чат модераторов 2.5b).
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.deals.api import DealsApi, SettleDisputeIn
from app.modules.moderation.application.ports import CaseRepository, ModerationPolicy
from app.modules.moderation.application.use_cases.decide_case import (
    CaseDecider,
    DecideCaseCommand,
)
from app.modules.moderation.domain.cases import CaseStatus, EntityType
from app.modules.moderation.domain.sanctions import SanctionStep, Severity
from app.modules.moderation.errors import CaseKindError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CaseId, DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveDisputeCommand:
    case_id: CaseId
    outcome: str
    """`completed` или `cancelled` — каким станет статус сделки."""
    reason_code: str
    """Машинный код причины: `work_done`, `no_show`, `poor_quality`, `prepayment_scam`, …"""
    moderator_id: UserId
    severity: Severity | None = None
    """Санкция второй стороне по лестнице; None — без санкции."""
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeResolution:
    case_id: CaseId
    dispute_id: UUID
    deal_id: DealId
    outcome: str
    case_status: CaseStatus
    sanction: SanctionStep | None


class ResolveDispute:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        decider: CaseDecider,
        deals: DealsApi,
        policy: ModerationPolicy,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._cases, self._decider, self._deals = uow, cases, decider, deals
        self._policy, self._audit, self._clock = policy, audit, clock

    async def __call__(self, cmd: ResolveDisputeCommand) -> DisputeResolution:
        policy_version = await self._policy.version()
        now = self._clock.now()
        async with self._uow:
            # порядок блокировок: кейс, затем сделка и спор (фасад deals)
            case = await self._cases.get_for_update(cmd.case_id)
            if case.entity_type is not EntityType.DISPUTE:
                raise CaseKindError(entity_type=case.entity_type.value)
            dispute = await self._deals.settle_dispute(
                SettleDisputeIn(
                    dispute_id=case.entity_id,
                    outcome=cmd.outcome,
                    reason_code=cmd.reason_code,
                    moderator_id=cmd.moderator_id,
                )
            )
            verdict = (
                ModerationDecision.REJECTED
                if cmd.severity is not None
                else ModerationDecision.APPROVED
            )
            decision = await self._decider.decide(
                case,
                DecideCaseCommand(
                    case_id=case.id,
                    verdict=verdict,
                    reason_code=cmd.reason_code,
                    severity=cmd.severity,
                    moderator_id=cmd.moderator_id,
                    note=cmd.note,
                ),
                policy_version=policy_version,
                now=now,
            )
            await self._audit.record(
                AuditEntry(
                    action="moderation.dispute.resolved",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.moderator_id,
                    entity_type="deals.dispute",
                    entity_id=dispute.id,
                    changes={"outcome": cmd.outcome, "reason_code": cmd.reason_code},
                )
            )
        return DisputeResolution(
            case_id=case.id,
            dispute_id=dispute.id,
            deal_id=dispute.deal_id,
            outcome=cmd.outcome,
            case_status=decision.status,
            sanction=decision.sanction,
        )
