"""Решение по кейсу (ADR-0016 §4, ARCHITECTURE §14.4): статус, код причины, версия
политики, ступень санкции — в одной транзакции.

- `approved` — нарушения нет. `rejected` — нарушение: автору уходит statement of reasons
  (ModerationDecisionMade → уведомление `moderation.decision`), а при `severity` — ступень
  лестницы санкций (domain/sanctions.py). Санкцию на аккаунт ставит только фасад identity
  (`restrict`, событие UserRestricted → уведомление `account.restricted`); предупреждение
  ничего не запрещает и лишь опускает уровень доверия (`record_violation`).
- Кейс с жалобой среди поводов, решённый `rejected`, — подтверждённая жалоба: сигнал риска
  `report_confirmed` и нарушение для уровня доверия.
- Объект кейса (2.6): одобрение публикует его, если он ждал проверки, и снимает заморозку,
  которую поставила автопроверка; отказ скрывает его. Через адаптер цели — фасад модуля.
- Решение и санкция пишутся в audit_log. Роль модератора проверяет точка входа (2.5b, 2.7).
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi, RestrictionIn
from app.modules.moderation.application.dto import CaseDecision
from app.modules.moderation.application.ports import (
    CaseRepository,
    ModerationPolicy,
    ModerationTargets,
    RiskSignals,
    SanctionRepository,
)
from app.modules.moderation.domain.cases import Case, CaseTrigger
from app.modules.moderation.domain.risk import RiskSignal, RiskSignalKind
from app.modules.moderation.domain.sanctions import (
    EFFECTS,
    Sanction,
    SanctionStep,
    Severity,
    next_step,
)
from app.modules.moderation.errors import InvalidDecisionError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ProgrammingError
from app.platform.kernel.ids import CaseId, RestrictionId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DecideCaseCommand:
    case_id: CaseId
    verdict: ModerationDecision
    reason_code: str | None = None
    """Машинный код причины (`prepayment_scam`, `contact_leak`, …); при отказе обязателен."""
    severity: Severity | None = None
    """Тяжесть нарушения для лестницы санкций; None — без санкции (только скрыть контент)."""
    moderator_id: UserId | None = None
    """None — решила автопроверка (2.6)."""
    note: str | None = None


class DecideCase:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        sanctions: SanctionRepository,
        signals: RiskSignals,
        identity: IdentityApi,
        targets: ModerationTargets,
        policy: ModerationPolicy,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._cases, self._sanctions, self._signals = uow, cases, sanctions, signals
        self._identity, self._targets, self._policy = identity, targets, policy
        self._audit, self._clock = audit, clock

    async def __call__(self, cmd: DecideCaseCommand) -> CaseDecision:
        if cmd.severity is not None and cmd.verdict is not ModerationDecision.REJECTED:
            raise InvalidDecisionError(field="severity")
        policy_version = await self._policy.version()
        now = self._clock.now()
        actor = ActorKind.STAFF if cmd.moderator_id is not None else ActorKind.SYSTEM
        async with self._uow:
            case = await self._cases.get_for_update(cmd.case_id)
            step = None
            if cmd.severity is not None:
                counted = await self._sanctions.counted(case.subject_id, now)
                step = next_step(cmd.severity, counted)
            case.decide(
                verdict=cmd.verdict,
                reason_code=cmd.reason_code,
                policy_version=policy_version,
                now=now,
                by=cmd.moderator_id,
                sanction=step,
                note=cmd.note,
            )
            await self._cases.save(case)
            await self._apply_to_target(case, cmd.verdict)
            restriction_id = None
            if step is not None:
                restriction_id = await self._impose(case, step, cmd.moderator_id, now=now)
            if cmd.verdict is ModerationDecision.REJECTED and case.reported:
                await self._confirm_report(case, sanctioned=step is not None)
            await self._audit.record(
                AuditEntry(
                    action="moderation.case.decided",
                    actor_kind=actor,
                    actor_id=cmd.moderator_id,
                    entity_type="moderation.case",
                    entity_id=case.id,
                    changes={
                        "status": case.status.value,
                        "reason_code": case.reason_code,
                        "policy_version": policy_version,
                        "sanction": step.value if step is not None else None,
                    },
                )
            )
        return CaseDecision(
            case_id=case.id, status=case.status, sanction=step, restriction_id=restriction_id
        )

    async def _apply_to_target(self, case: Case, verdict: ModerationDecision) -> None:
        if case.trigger is CaseTrigger.APPEAL:
            return  # итог апелляции — 2.5b
        if verdict is ModerationDecision.APPROVED:
            await self._identity.lift_case_restrictions(case.id)  # заморозка автопроверки
        target = self._targets.get(case.entity_type)
        if target is None:
            return  # аккаунт или модуль, ещё не подключённый к конвейеру
        if verdict is ModerationDecision.APPROVED:
            await target.publish(case.entity_id)
        else:
            await target.hide(case.entity_id, reason_code=case.reason_code or "other")

    async def _impose(
        self, case: Case, step: SanctionStep, moderator_id: UserId | None, *, now: datetime
    ) -> RestrictionId | None:
        effect = EFFECTS.get(step)
        restriction_id = None
        if effect is None:  # предупреждение
            await self._identity.record_violation(case.subject_id)
        else:
            if case.reason_code is None:  # отказ без причины не пропускает Case.decide
                raise ProgrammingError(f"rejected case {case.id} has no reason_code")
            restriction_id = await self._identity.restrict(
                RestrictionIn(
                    user_id=case.subject_id,
                    kind=effect.kind,
                    reason_code=case.reason_code,
                    ends_at=now + effect.duration if effect.duration is not None else None,
                    case_id=case.id,
                    created_by=moderator_id,
                )
            )
        await self._sanctions.add(
            Sanction.impose(
                user_id=case.subject_id,
                case_id=case.id,
                step=step,
                now=now,
                restriction_id=restriction_id,
            )
        )
        await self._audit.record(
            AuditEntry(
                action="moderation.sanction.imposed",
                actor_kind=ActorKind.STAFF if moderator_id is not None else ActorKind.SYSTEM,
                actor_id=moderator_id,
                entity_type="identity.user",
                entity_id=case.subject_id,
                changes={
                    "case_id": str(case.id),
                    "step": step.value,
                    "restriction": effect.kind.value if effect is not None else None,
                },
            )
        )
        return restriction_id

    async def _confirm_report(self, case: Case, *, sanctioned: bool) -> None:
        await self._signals.add(
            [
                RiskSignal(
                    user_id=case.subject_id,
                    kind=RiskSignalKind.REPORT_CONFIRMED,
                    ref_type="moderation.case",
                    ref_id=case.id,
                    dedupe_key=f"{RiskSignalKind.REPORT_CONFIRMED}:{case.id}",
                )
            ]
        )
        if not sanctioned:  # санкция уже опустила уровень доверия
            await self._identity.record_violation(case.subject_id)
