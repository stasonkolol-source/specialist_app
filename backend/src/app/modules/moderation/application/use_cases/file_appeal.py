"""Обжаловать решение модерации (POST /appeals, S49b «Обжаловать»; DEVELOPMENT_PLAN 2.5b;
ARCHITECTURE §14.4).

1. Какое решение: `case_id` — явно (кнопка «Обжаловать» уведомления), иначе — решение последней
   неотменённой санкции пользователя; с экрана S49b приходит вид санкции (`restriction`), и
   берётся последняя ступень с таким действием. Нечего обжаловать — 404
   `appeal_target_not_found`; прошло шесть месяцев — 409 `appeal_window_closed`
   (domain/appeals.py).
2. Апелляция на решение одна: повтор отдаёт её же (`created` False — «уже обжаловано»), в том
   числе уже рассмотренную. Два запроса разом: второй получает AppealAlreadyFiledError на
   вставке и повторяет команду — уже находя первую.
3. Апелляция — кейс очереди Appeals (≤ 72 ч) об объекте обжалованного решения: доказательства
   того решения остаются под legal hold, пока она открыта. Кейс публикует CaseOpened — карточка
   в чате модераторов.
"""

from dataclasses import dataclass

from app.modules.moderation.application.ports import CaseRepository, SanctionRepository
from app.modules.moderation.domain.appeals import check_appealable
from app.modules.moderation.domain.cases import Case, CaseTrigger
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import EFFECTS, SanctionStep
from app.modules.moderation.errors import AppealTargetNotFoundError, CaseNotFoundError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CaseId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class FileAppealCommand:
    user_id: UserId
    case_id: CaseId | None = None
    """Решение явно; None — по санкции."""
    restriction: RestrictionKind | None = None
    """Вид санкции с экрана S49b: чьё решение обжаловать, если `case_id` нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FiledAppeal:
    appeal: Case
    created: bool
    """False — апелляция на это решение уже была: «уже обжаловано»."""


class FileAppeal:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        sanctions: SanctionRepository,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._cases, self._sanctions = uow, cases, sanctions
        self._audit, self._clock = audit, clock

    async def __call__(self, cmd: FileAppealCommand) -> FiledAppeal:
        return await retry_on_conflict(lambda: self._file(cmd))

    async def _file(self, cmd: FileAppealCommand) -> FiledAppeal:
        now = self._clock.now()
        async with self._uow:
            decision_id = cmd.case_id or await self._sanctions.latest_case(
                cmd.user_id, _steps(cmd.restriction)
            )
            if decision_id is None:
                raise AppealTargetNotFoundError
            try:
                decision = await self._cases.get_for_update(decision_id)
            except CaseNotFoundError:
                raise AppealTargetNotFoundError from None
            found = await self._cases.appeal_for(decision.id)
            if found is not None and found.subject_id == cmd.user_id:
                return FiledAppeal(appeal=found, created=False)
            check_appealable(decision, cmd.user_id, now)
            appeal = Case.open(
                queue=Queue.APPEALS,
                entity_type=decision.entity_type,
                entity_id=decision.entity_id,
                subject_id=cmd.user_id,
                trigger=CaseTrigger.APPEAL,
                now=now,
                details={
                    "appeal_of": str(decision.id),
                    "reason_code": decision.reason_code,
                    # в `cli moderation-queue` — что обжалуют: «appeal:prepayment_scam»
                    "signals": [f"appeal:{decision.reason_code}"],
                },
                media_ids=decision.media_ids,
                appeal_of=decision.id,
            )
            await self._cases.add(appeal)
            await self._audit.record(
                AuditEntry(
                    action="moderation.appeal.filed",
                    actor_kind=ActorKind.USER,
                    actor_id=cmd.user_id,
                    entity_type="moderation.case",
                    entity_id=appeal.id,
                    changes={"appeal_of": str(decision.id)},
                )
            )
        return FiledAppeal(appeal=appeal, created=True)


def _steps(restriction: RestrictionKind | None) -> frozenset[SanctionStep]:
    """Ступени, чью санкцию обжалуют: с экрана S49b — с этим видом санкции; без него — все."""
    if restriction is None:
        return frozenset(SanctionStep)
    return frozenset(step for step, effect in EFFECTS.items() if effect.kind is restriction)
