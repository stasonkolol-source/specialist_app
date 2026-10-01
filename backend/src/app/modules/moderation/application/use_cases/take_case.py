"""Модератор берёт кейс в работу или отдаёт старшему (чат модераторов — 2.5b, админка — 2.7).

Роль персонала проверяет точка входа (кнопка в чате, SQLAdmin): здесь — только переходы
кейса и запись в журнал аудита.
"""

from dataclasses import dataclass

from app.modules.moderation.application.ports import CaseRepository
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class TakeCaseCommand:
    case_id: CaseId
    moderator_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class EscalateCaseCommand:
    case_id: CaseId
    moderator_id: UserId
    note: str | None = None


class TakeCase:
    def __init__(self, uow: UnitOfWork, cases: CaseRepository, audit: AuditLog) -> None:
        self._uow, self._cases, self._audit = uow, cases, audit

    async def __call__(self, cmd: TakeCaseCommand) -> None:
        async with self._uow:
            case = await self._cases.get_for_update(cmd.case_id)
            case.take(cmd.moderator_id)
            await self._cases.save(case)
            await self._audit.record(
                AuditEntry(
                    action="moderation.case.taken",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.moderator_id,
                    entity_type="moderation.case",
                    entity_id=case.id,
                )
            )


class EscalateCase:
    def __init__(self, uow: UnitOfWork, cases: CaseRepository, audit: AuditLog) -> None:
        self._uow, self._cases, self._audit = uow, cases, audit

    async def __call__(self, cmd: EscalateCaseCommand) -> None:
        async with self._uow:
            case = await self._cases.get_for_update(cmd.case_id)
            case.escalate(cmd.moderator_id, note=cmd.note)
            await self._cases.save(case)
            await self._audit.record(
                AuditEntry(
                    action="moderation.case.escalated",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.moderator_id,
                    entity_type="moderation.case",
                    entity_id=case.id,
                )
            )
