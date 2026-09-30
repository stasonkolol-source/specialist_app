"""События модуля moderation (ADR-0020 §2). Публикует модуль moderation (шаг 2.5a).

`ModerationDecision` — часть published language: подписчики (уведомления) решают по нему,
писать ли автору.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CaseId, UserId


class ModerationDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModerationDecisionMade(DomainEvent):
    """Кейс модерации решён: модератором или автопроверкой (moderation.cases).

    `author_id` — чей контент; при отказе ему уходит уведомление `moderation.decision`.
    `entity_type` — что проверяли: `job`, `profile`, `response`, `review`, `message`,
    `media`, `user` (как `moderation.cases.entity_type`). `decision_code` — машинный код
    причины: метки ADR-0016 (`contact_leak`, `spam_ad`, `prepayment_scam`, …) или `other`.
    """

    event_type = "moderation.ModerationDecisionMade"
    case_id: CaseId
    author_id: UserId
    entity_type: str
    entity_id: UUID
    decision: ModerationDecision
    decision_code: str | None = None
