"""Пожаловаться (POST /reports, шторка S46; DEVELOPMENT_PLAN 4.7; ARCHITECTURE §14.2).

1. Причина — из списка своего типа объекта (domain/reports.py), иначе 422 `invalid_report`.
2. На кого — автор объекта, который жалующийся видит (адаптер ReportTargets): не видит — 404
   `report_target_not_found`; свой объект — 422. Жалоба на собеседника из чата S30 несёт диалог:
   по нему модератор откроет переписку; диалог не с этим человеком — 422.
3. Открытая жалоба того же человека на тот же объект — она же: повтор не тратит лимит и не
   дописывает в кейс второй повод.
4. Лимит — двадцать жалоб в сутки (429 `reports_limit`). Жалоба открывает кейс об объекте или
   дописывается поводом в открытый (CaseOpener): угрозы, запрещённое и незаконное — P0,
   остальное — P1. В повод — причина и id, без текста жалобы (он остаётся в самой жалобе).
5. Жалоба, кейс и ReportCreated (аналитика `report_created`) — одной транзакцией. Карточка в
   чате модераторов — с 2.5b; до неё кейс виден в `cli moderation-queue`.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.moderation.application.ports import ReportQuota, ReportRepository, ReportTargets
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import (
    MAX_COMMENT,
    Report,
    ReportReason,
    ReportStatus,
    check_reason,
    report_queue,
)
from app.modules.moderation.errors import InvalidReportError, ReportTargetNotFoundError
from app.platform.contracts.events.moderation import ReportCreated
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReportCommand:
    reporter_id: UserId
    target_type: EntityType
    target_id: UUID
    reason: ReportReason
    comment: str | None = None
    conversation_id: UUID | None = None
    """Диалог, в котором всё случилось (меню чата S30): модератору — где читать переписку."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FiledReport:
    report: Report
    queue: Queue
    """Очередь по причине: P0 — «в течение часа», P1 — «в течение 2 часов» (S46)."""
    created: bool
    """False — открытая жалоба уже была: повтор."""


class CreateReport:
    def __init__(
        self,
        uow: UnitOfWork,
        reports: ReportRepository,
        targets: ReportTargets,
        quota: ReportQuota,
        opener: CaseOpener,
        clock: Clock,
    ) -> None:
        self._uow, self._reports, self._targets = uow, reports, targets
        self._quota, self._opener, self._clock = quota, opener, clock

    async def __call__(self, cmd: CreateReportCommand) -> FiledReport:
        check_reason(cmd.target_type, cmd.reason)
        if cmd.comment is not None and len(cmd.comment) > MAX_COMMENT:
            raise InvalidReportError(field="comment", reason="too_long")
        subject = await self._targets.subject(cmd.target_type, cmd.target_id, cmd.reporter_id)
        if subject is None:
            raise ReportTargetNotFoundError(target_type=cmd.target_type.value)
        if subject == cmd.reporter_id:
            raise InvalidReportError(field="target_id", reason="own")
        if cmd.conversation_id is not None and (
            await self._targets.counterpart(cmd.conversation_id, cmd.reporter_id) != subject
        ):
            raise InvalidReportError(field="conversation_id", reason="not_with_target")
        return await retry_on_conflict(lambda: self._file(cmd, subject))

    async def _file(self, cmd: CreateReportCommand, subject: UserId) -> FiledReport:
        queue = report_queue(cmd.reason)
        async with self._uow:
            found = await self._reports.open_of(cmd.reporter_id, cmd.target_type, cmd.target_id)
            if found is not None:
                return FiledReport(report=found, queue=report_queue(found.reason), created=False)
            await self._quota.take(cmd.reporter_id)
            report_id = new_id()
            details: dict[str, object] = {
                "report_id": str(report_id),
                "reporter_id": str(cmd.reporter_id),
                "reason": cmd.reason.value,
                # в `cli moderation-queue` — что случилось: «report:fraud»
                "signals": [f"report:{cmd.reason.value}"],
            }
            if cmd.conversation_id is not None:
                details["conversation_id"] = str(cmd.conversation_id)
            case_id = await self._opener.open(
                OpenCaseCommand(
                    queue=queue,
                    entity_type=cmd.target_type,
                    entity_id=cmd.target_id,
                    subject_id=subject,
                    trigger=CaseTrigger.REPORT,
                    details=details,
                )
            )
            now = self._clock.now()
            report = Report(
                id=report_id,
                reporter_id=cmd.reporter_id,
                target_type=cmd.target_type,
                target_id=cmd.target_id,
                reason=cmd.reason,
                comment=_comment(cmd.comment),
                case_id=case_id,
                status=ReportStatus.OPEN,
                created_at=now,
            )
            await self._reports.add(report)
            self._uow.add_event(
                ReportCreated(
                    report_id=report.id,
                    reporter_id=cmd.reporter_id,
                    target_type=cmd.target_type.value,
                    target_id=cmd.target_id,
                    reason=cmd.reason.value,
                    case_id=case_id,
                    queue=queue.value,
                    occurred_at=now,
                )
            )
        return FiledReport(report=report, queue=queue, created=True)


def _comment(text: str | None) -> str | None:
    """Пустые «Подробности» — без комментария."""
    stripped = text.strip() if text else ""
    return stripped or None
