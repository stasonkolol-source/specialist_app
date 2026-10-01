"""Открыть кейс модерации (ARCHITECTURE §14.2): автопроверки (2.6), жалобы (4.7),
апелляции (2.5b), споры (6.1c).

У объекта один открытый кейс: второй повод дописывается в него — очередь строже из двух,
срок ближе, файлы-доказательства добавляются. Два повода одновременно: второй получает
CaseAlreadyOpenError на вставке и повторяет команду — уже дописывая в открытый кейс.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.moderation.application.ports import CaseRepository
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CaseId, MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenCaseCommand:
    queue: Queue
    entity_type: EntityType
    entity_id: UUID
    subject_id: UserId
    """Чей контент или аккаунт."""
    trigger: CaseTrigger
    details: Mapping[str, object] = field(default_factory=dict)
    """Что сработало: правила, метки классификатора, жалоба — без текста контента."""
    media_ids: Sequence[MediaId] = ()
    appeal_of: CaseId | None = None


class CaseOpener:
    """Открыть кейс или дописать повод в открытый — в транзакции вызывающего (автопроверка
    открывает кейс вместе с публикацией или скрытием объекта)."""

    def __init__(self, cases: CaseRepository, audit: AuditLog, clock: Clock) -> None:
        self._cases, self._audit, self._clock = cases, audit, clock

    async def open(self, cmd: OpenCaseCommand) -> CaseId:
        now = self._clock.now()
        case = await self._cases.open_for_entity(cmd.entity_type, cmd.entity_id)
        if case is not None:
            case.add_trigger(
                queue=cmd.queue,
                trigger=cmd.trigger,
                now=now,
                details=cmd.details,
                media_ids=cmd.media_ids,
            )
            await self._cases.save(case)
            return case.id
        case = Case.open(
            queue=cmd.queue,
            entity_type=cmd.entity_type,
            entity_id=cmd.entity_id,
            subject_id=cmd.subject_id,
            trigger=cmd.trigger,
            now=now,
            details=cmd.details,
            media_ids=cmd.media_ids,
            appeal_of=cmd.appeal_of,
        )
        await self._cases.add(case)
        await self._audit.record(
            AuditEntry(
                action="moderation.case.opened",
                actor_kind=ActorKind.SYSTEM,
                entity_type="moderation.case",
                entity_id=case.id,
                changes={"queue": case.queue.value, "trigger": case.trigger.value},
            )
        )
        return case.id


class OpenCase:
    def __init__(self, uow: UnitOfWork, opener: CaseOpener) -> None:
        self._uow, self._opener = uow, opener

    async def __call__(self, cmd: OpenCaseCommand) -> CaseId:
        return await retry_on_conflict(lambda: self._open(cmd))

    async def _open(self, cmd: OpenCaseCommand) -> CaseId:
        async with self._uow:
            return await self._opener.open(cmd)
