"""Кейс модерации — единица работы модератора (ARCHITECTURE §14.2, ADR-0016 §4).

Кейс открывают автопроверки (2.6), жалобы (4.7), апелляции (2.5b) и споры (6.1c). У объекта
один открытый кейс: новый повод добавляется в него, очередь — строже из двух, срок — ближе.

Жизненный цикл:
    pending → in_review → approved | rejected
    pending | in_review → escalated → in_review → …
    pending → approved | rejected        (автопроверка решает сама, 2.6)
`approved` — нарушения нет; `rejected` — нарушение: контент скрыт, санкция — по лестнице
(domain/sanctions.py). Решение пишет машинный код причины и версию политики модерации и
публикует ModerationDecisionMade — statement of reasons для автора. Итог апелляции — 2.5b.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.moderation.domain.queues import Queue, stricter
from app.modules.moderation.domain.sanctions import SanctionStep
from app.modules.moderation.domain.sla import due_at
from app.modules.moderation.errors import CaseStateError, CaseTakenError, InvalidDecisionError
from app.platform.contracts.events.moderation import ModerationDecision, ModerationDecisionMade
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id

MAX_REASON_CODE = 64
_REASON_CODE: Final = re.compile(r"[a-z][a-z0-9_.]*")
"""Как у санкций identity: причина решения становится причиной санкции."""


class EntityType(StrEnum):
    """Что проверяем (как `ModerationDecisionMade.entity_type` и цели жалоб)."""

    USER = "user"
    PROFILE = "profile"
    JOB = "job"
    RESPONSE = "response"
    REVIEW = "review"
    REVIEW_REPLY = "review_reply"
    """Ответ исполнителя на отзыв (7.2): проверяется отдельно, нарушение скрывает только его."""
    MESSAGE = "message"
    MEDIA = "media"


class CaseTrigger(StrEnum):
    NEW_CONTENT = "new_content"
    EDIT = "edit"
    REPORT = "report"
    AUTO_FLAG = "auto_flag"
    APPEAL = "appeal"


class CaseStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    ESCALATED = "escalated"
    APPROVED = "approved"
    REJECTED = "rejected"


OPEN: Final = frozenset({CaseStatus.PENDING, CaseStatus.IN_REVIEW, CaseStatus.ESCALATED})
"""Открытый кейс держит legal hold (ADR-0016 §6) и не даёт открыть второй на объект."""

_VERDICT: Final[Mapping[ModerationDecision, CaseStatus]] = {
    ModerationDecision.APPROVED: CaseStatus.APPROVED,
    ModerationDecision.REJECTED: CaseStatus.REJECTED,
}


@dataclass(eq=False, kw_only=True)
class Case(AggregateRoot):
    id: CaseId
    queue: Queue
    entity_type: EntityType
    entity_id: UUID
    subject_id: UserId
    """Чей контент или аккаунт проверяем: ему — решение и санкция."""
    trigger: CaseTrigger
    """Первый повод; все поводы — в `evidence`."""
    status: CaseStatus
    opened_at: datetime
    due_at: datetime
    evidence: list[dict[str, object]] = field(default_factory=list)
    """Поводы по порядку: что сработало (правила, классификаторы, жалоба) и когда."""
    media_ids: tuple[MediaId, ...] = ()
    """Файлы объекта на момент повода: доказательства под legal hold, пока кейс открыт."""
    appeal_of: CaseId | None = None
    assigned_to: UserId | None = None
    decided_by: UserId | None = None
    """Модератор; None — решила автопроверка."""
    reason_code: str | None = None
    policy_version: str | None = None
    decided_at: datetime | None = None
    notes: str | None = None

    @classmethod
    def open(
        cls,
        *,
        queue: Queue,
        entity_type: EntityType,
        entity_id: UUID,
        subject_id: UserId,
        trigger: CaseTrigger,
        now: datetime,
        details: Mapping[str, object] | None = None,
        media_ids: Iterable[MediaId] = (),
        appeal_of: CaseId | None = None,
    ) -> Case:
        return cls(
            id=CaseId(new_id()),
            queue=queue,
            entity_type=entity_type,
            entity_id=entity_id,
            subject_id=subject_id,
            trigger=trigger,
            status=CaseStatus.PENDING,
            opened_at=now,
            due_at=due_at(queue, now),
            evidence=[_evidence(trigger, now, details)],
            media_ids=tuple(dict.fromkeys(media_ids)),
            appeal_of=appeal_of,
        )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN

    @property
    def reported(self) -> bool:
        """Среди поводов есть жалоба: отказ по такому кейсу — подтверждённая жалоба."""
        return any(entry.get("trigger") == CaseTrigger.REPORT.value for entry in self.evidence)

    def add_trigger(
        self,
        *,
        queue: Queue,
        trigger: CaseTrigger,
        now: datetime,
        details: Mapping[str, object] | None = None,
        media_ids: Iterable[MediaId] = (),
    ) -> None:
        """Ещё один повод по тому же объекту: очередь строже из двух, срок — ближний."""
        self._ensure_open()
        self.queue = stricter(queue, self.queue)
        self.due_at = min(self.due_at, due_at(queue, now))
        self.evidence.append(_evidence(trigger, now, details))
        self.media_ids = tuple(dict.fromkeys((*self.media_ids, *media_ids)))

    def take(self, moderator: UserId) -> None:
        """Модератор взял кейс в работу; повтор тем же модератором ничего не меняет."""
        if self.status is CaseStatus.IN_REVIEW:
            if self.assigned_to != moderator:
                raise CaseTakenError(case_id=self.id)
            return
        self._ensure_open()
        self.status = CaseStatus.IN_REVIEW
        self.assigned_to = moderator

    def escalate(self, by: UserId, *, note: str | None = None) -> None:
        """Старшему: кейс снова свободен, его берёт администратор."""
        if self.status is CaseStatus.ESCALATED:
            return
        self._ensure_open()
        if self.status is CaseStatus.IN_REVIEW and self.assigned_to != by:
            raise CaseTakenError(case_id=self.id)
        self.status = CaseStatus.ESCALATED
        self.assigned_to = None
        if note:
            self.notes = f"{self.notes}\n{note}" if self.notes else note

    def decide(
        self,
        *,
        verdict: ModerationDecision,
        reason_code: str | None,
        policy_version: str,
        now: datetime,
        by: UserId | None,
        sanction: SanctionStep | None = None,
        note: str | None = None,
    ) -> None:
        """Решение: модератором (`by`) или автопроверкой (`by` None — только из очереди)."""
        self._ensure_open()
        if by is None and self.status is not CaseStatus.PENDING:
            raise CaseStateError(case_id=self.id, status=self.status.value)
        if by is not None and self.status is CaseStatus.IN_REVIEW and self.assigned_to != by:
            raise CaseTakenError(case_id=self.id)
        if reason_code is not None and (
            len(reason_code) > MAX_REASON_CODE or not _REASON_CODE.fullmatch(reason_code)
        ):
            raise InvalidDecisionError(field="reason_code")
        if verdict is ModerationDecision.REJECTED and reason_code is None:
            raise InvalidDecisionError(field="reason_code")
        if sanction is not None and verdict is not ModerationDecision.REJECTED:
            raise InvalidDecisionError(field="sanction")
        self.status = _VERDICT[verdict]
        self.decided_by = by
        self.reason_code = reason_code
        self.policy_version = policy_version
        self.decided_at = now
        if note:
            self.notes = f"{self.notes}\n{note}" if self.notes else note
        if self.trigger is CaseTrigger.APPEAL:
            return  # итог апелляции и его уведомление — 2.5b
        self._record(
            ModerationDecisionMade(
                case_id=self.id,
                author_id=self.subject_id,
                entity_type=self.entity_type.value,
                entity_id=self.entity_id,
                decision=verdict,
                decision_code=reason_code,
                automated=by is None,
                sanction=sanction.value if sanction is not None else None,
                occurred_at=now,
            )
        )

    def _ensure_open(self) -> None:
        if not self.is_open:
            raise CaseStateError(case_id=self.id, status=self.status.value)


def _evidence(
    trigger: CaseTrigger, now: datetime, details: Mapping[str, object] | None
) -> dict[str, object]:
    return {"trigger": trigger.value, "at": now.isoformat(), **(details or {})}
