"""Жалобы пользователей (ARCHITECTURE §7.3 `moderation.reports`, §14.2, ADR-0016 §4, ADR-0018;
DEVELOPMENT_PLAN 4.7).

Жалоба — повод кейса модерации об объекте: профиле специалиста, заявке, отзыве, сообщении или
самом пользователе (меню чата S30). Причины — свои у каждого типа объекта (шторка S46);
угрозы и оскорбления, запрещённые услуги и незаконное — очередь P0, остальное — P1 (в MVP туда
же заявления третьих лиц: `is_legal_notice` и срок `due_at` — задел v1).

Жалоба открыта, пока открыт её кейс: повтор того же человека на тот же объект — та же жалоба,
без второго повода в кейсе. Решение по кейсу закрывает его жалобы: нарушение — `resolved`
(подтверждённая), нет нарушения — `rejected`. Новая жалоба после решения — снова повод.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.errors import InvalidReportError
from app.platform.kernel.ids import CaseId, UserId


class ReportReason(StrEnum):
    SPAM = "spam"
    FRAUD = "fraud"
    PROHIBITED = "prohibited"
    OFFENSIVE = "offensive"
    FAKE_PROFILE = "fake_profile"
    NO_SHOW = "no_show"
    PERSONAL_DATA = "personal_data"
    DEFAMATION = "defamation"
    COPYRIGHT = "copyright"
    ILLEGAL = "illegal"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    """Кейс решён «нарушение»: жалоба подтверждена."""
    REJECTED = "rejected"
    """Кейс решён «нарушения нет»."""


_R = ReportReason
REASONS: Final[Mapping[EntityType, tuple[ReportReason, ...]]] = {
    # шторка S46 на карточке специалиста — как на артборде
    EntityType.PROFILE: (_R.FRAUD, _R.FAKE_PROFILE, _R.OFFENSIVE, _R.PROHIBITED, _R.OTHER),
    EntityType.JOB: (_R.FRAUD, _R.PROHIBITED, _R.SPAM, _R.OFFENSIVE, _R.OTHER),
    EntityType.REVIEW: (_R.DEFAMATION, _R.OFFENSIVE, _R.PERSONAL_DATA, _R.SPAM, _R.OTHER),
    EntityType.MESSAGE: (_R.FRAUD, _R.OFFENSIVE, _R.SPAM, _R.PERSONAL_DATA, _R.OTHER),
    # собеседник из меню чата S30: «не пришёл» — только о человеке, не об объекте
    EntityType.USER: (_R.FRAUD, _R.OFFENSIVE, _R.NO_SHOW, _R.SPAM, _R.FAKE_PROFILE, _R.OTHER),
}
"""На что можно пожаловаться и какие причины у каждого типа; порядок — как в шторке."""

SAFETY_REASONS: Final = frozenset({_R.OFFENSIVE, _R.PROHIBITED, _R.ILLEGAL})
"""Угрозы, запрещённые услуги, незаконное — очередь P0 (§14.2); остальное — P1."""

MAX_COMMENT: Final = 1000
DAILY_REPORTS: Final = 20
"""Жалоб в сутки от одного человека (§13.3, DSA Art. 23): двадцать первая — 429."""


def report_queue(reason: ReportReason) -> Queue:
    return Queue.SAFETY if reason in SAFETY_REASONS else Queue.FRAUD


def check_reason(target_type: EntityType, reason: ReportReason) -> None:
    """Причина — из списка своего типа объекта; на другие типы не жалуются (422)."""
    allowed = REASONS.get(target_type)
    if allowed is None:
        raise InvalidReportError(field="target_type", reason="unsupported")
    if reason not in allowed:
        raise InvalidReportError(field="reason", reason="not_for_target")


@dataclass(frozen=True, slots=True, kw_only=True)
class Report:
    id: UUID
    reporter_id: UserId
    target_type: EntityType
    target_id: UUID
    reason: ReportReason
    comment: str | None
    case_id: CaseId | None
    status: ReportStatus
    created_at: datetime
