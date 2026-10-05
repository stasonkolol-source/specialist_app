"""Решение по кейсу (ADR-0016 §4, ARCHITECTURE §14.4): статус, код причины, версия
политики, ступень санкции — в одной транзакции.

- `approved` — нарушения нет. `rejected` — нарушение: автору уходит statement of reasons
  (ModerationDecisionMade → уведомление `moderation.decision`), а при `severity` — ступень
  лестницы санкций (domain/sanctions.py). Санкцию на аккаунт ставит только фасад identity
  (`restrict`, событие UserRestricted → уведомление `account.restricted`); предупреждение
  ничего не запрещает и лишь опускает уровень доверия (`record_violation`).
- Кейс с жалобой среди поводов, решённый `rejected`, — подтверждённая жалоба: сигнал риска
  `report_confirmed` и нарушение для уровня доверия. Решение закрывает жалобы кейса (4.7):
  нарушение — `resolved`, нет нарушения — `rejected`; ответ жалующемуся — с 2.5b.
- Объект кейса (2.6): одобрение публикует его, если он ждал проверки, и снимает заморозку,
  которую поставила автопроверка; отказ скрывает его. Через адаптер цели — фасад модуля.
  Одобрение публикует только версию, которую показывает карточка (`Case.entity_version`, QA
  ADV-11): фасад сверяет её под блокировкой строки объекта. Объект уже в другой версии (автор
  правил после карточки, а автопроверка правки ещё не дошла) — решения нет: кейс закрыт как
  устаревший, открыт новый о новой версии (новая карточка), ответ — CaseSupersededError.
- Апелляция (2.5b): `approved` — удовлетворена: санкции обжалованного решения сняты (фасад
  identity `lift_case_restrictions`, событие UserRestrictionsLifted), его ступени лестницы
  отменены и больше не считаются; `rejected` — решение остаётся в силе. Санкции за апелляцию
  нет; автору — итог (AppealDecided → `moderation.decision`). Объект не трогается.
- Решение и санкция пишутся в audit_log. Роль модератора проверяет точка входа (`cli`, чат
  модераторов 2.5b, админка 2.7).
- Спор по сделке (6.1c) так не решить: у него обязателен исход сделки — ResolveDispute, который
  решает кейс тем же CaseDecider в своей транзакции.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi, RestrictionIn
from app.modules.moderation.application.dto import CaseDecision
from app.modules.moderation.application.ports import (
    CaseRepository,
    ModerationPolicy,
    ModerationTargets,
    ReportRepository,
    RiskSignals,
    SanctionRepository,
)
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.reports import ReportStatus
from app.modules.moderation.domain.risk import RiskSignal, RiskSignalKind
from app.modules.moderation.domain.sanctions import (
    EFFECTS,
    Sanction,
    SanctionStep,
    Severity,
    next_step,
)
from app.modules.moderation.errors import (
    CaseKindError,
    CaseSupersededError,
    InvalidDecisionError,
)
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


class CaseDecider:
    """Решение по кейсу в транзакции вызывающего: DecideCase и ResolveDispute (6.1c)."""

    def __init__(
        self,
        cases: CaseRepository,
        sanctions: SanctionRepository,
        signals: RiskSignals,
        identity: IdentityApi,
        targets: ModerationTargets,
        reports: ReportRepository,
        audit: AuditLog,
    ) -> None:
        self._cases, self._sanctions, self._signals = cases, sanctions, signals
        self._identity, self._targets, self._audit = identity, targets, audit
        self._reports = reports

    async def decide(
        self, case: Case, cmd: DecideCaseCommand, *, policy_version: str, now: datetime
    ) -> CaseDecision:
        """Кейс уже под блокировкой строки (get_for_update вызывающего)."""
        if cmd.severity is not None and (
            cmd.verdict is not ModerationDecision.REJECTED or case.is_appeal
        ):
            raise InvalidDecisionError(field="severity")
        actor = ActorKind.STAFF if cmd.moderator_id is not None else ActorKind.SYSTEM
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
        if case.appeal_of is not None and cmd.verdict is ModerationDecision.APPROVED:
            await self._grant_appeal(case.appeal_of, cmd.moderator_id, now=now)
        restriction_id = None
        if step is not None:
            restriction_id = await self._impose(case, step, cmd.moderator_id, now=now)
        if case.reported:
            violation = cmd.verdict is ModerationDecision.REJECTED
            if violation:
                await self._confirm_report(case, sanctioned=step is not None)
            await self._reports.close_for_case(
                case.id,
                status=ReportStatus.RESOLVED if violation else ReportStatus.REJECTED,
                resolved_by=cmd.moderator_id,
                resolution=case.reason_code,
                now=now,
            )
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
        if case.is_appeal:
            return  # апелляция пересматривает решение, а не объект
        if verdict is ModerationDecision.APPROVED:
            await self._identity.lift_case_restrictions(case.id)  # заморозка автопроверки
        target = self._targets.get(case.entity_type)
        if target is None:
            return  # аккаунт или модуль, ещё не подключённый к конвейеру
        if verdict is ModerationDecision.APPROVED:
            # только версию, которую видел модератор: правленую фасад не опубликует
            await target.publish(case.entity_id, version=case.entity_version)
        else:
            await target.hide(case.entity_id, reason_code=case.reason_code or "other")

    async def _grant_appeal(
        self, decision_id: CaseId, moderator_id: UserId | None, *, now: datetime
    ) -> None:
        lifted = await self._identity.lift_case_restrictions(decision_id)
        revoked = await self._sanctions.revoke_for_case(decision_id, now)
        await self._audit.record(
            AuditEntry(
                action="moderation.appeal.granted",
                actor_kind=ActorKind.STAFF if moderator_id is not None else ActorKind.SYSTEM,
                actor_id=moderator_id,
                entity_type="moderation.case",
                entity_id=decision_id,
                changes={"restrictions_lifted": lifted, "sanctions_revoked": revoked},
            )
        )

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


class DecideCase:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        decider: CaseDecider,
        opener: CaseOpener,
        targets: ModerationTargets,
        policy: ModerationPolicy,
        clock: Clock,
    ) -> None:
        self._uow, self._cases, self._decider = uow, cases, decider
        self._opener, self._targets = opener, targets
        self._policy, self._clock = policy, clock

    async def __call__(self, cmd: DecideCaseCommand) -> CaseDecision:
        if cmd.severity is not None and cmd.verdict is not ModerationDecision.REJECTED:
            raise InvalidDecisionError(field="severity")
        policy_version = await self._policy.version()
        current = await self._current_version(cmd.case_id)  # фасад читает в своей транзакции
        now = self._clock.now()
        async with self._uow:
            case = await self._cases.get_for_update(cmd.case_id)
            if case.entity_type is EntityType.DISPUTE and not case.is_appeal:
                # апелляцию на решение по спору решают как любую: сделку она не трогает
                raise CaseKindError(entity_type=case.entity_type.value)
            if not _stale(case, current):
                return await self._decider.decide(case, cmd, policy_version=policy_version, now=now)
            successor = await self._opener.supersede(
                case,
                OpenCaseCommand(
                    queue=case.queue,
                    entity_type=case.entity_type,
                    entity_id=case.entity_id,
                    subject_id=case.subject_id,
                    trigger=CaseTrigger.EDIT,
                    entity_version=current,
                ),
                now=now,
            )
        # новый кейс уже записан: решение по прежней версии — отказ
        raise CaseSupersededError(case_id=case.id, successor_id=successor.id)

    async def _current_version(self, case_id: CaseId) -> int | None:
        """Версия объекта сейчас; None — сверять не с чем (у кейса нет версии, объекта нет или
        он больше не ждёт проверки — тогда одобрение и так ничего не опубликует)."""
        case = await self._cases.get(case_id)
        if case is None or case.entity_version is None or case.is_appeal or not case.is_open:
            return None
        target = self._targets.get(case.entity_type)
        content = await target.content(case.entity_id) if target is not None else None
        return content.version if content is not None else None


def _stale(case: Case, current: int | None) -> bool:
    """Кейс показывает не ту версию, в которой объект сейчас. Кейс без версии (жалоба, кейс до
    версий) так не сверяется: одобрение публикует то, что ждёт проверки, как раньше."""
    return (
        case.is_open
        and not case.is_appeal
        and case.entity_version is not None
        and case.is_stale(current)
    )
