"""DTO модуля moderation (ADR-0020 §6)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.moderation.domain.cases import CaseStatus
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import SanctionStep
from app.platform.ai.port import ContentKind
from app.platform.kernel.ids import CaseId, RestrictionId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentCheck:
    """Текст на проверку правилами: заявка, отклик, сообщение, профиль или отзыв."""

    author_id: UserId
    kind: ContentKind
    content_id: UUID
    """Повторная проверка той же единицы контента не увеличивает счётчики velocity."""
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportRulesResult:
    """Счётчики импорта словаря из сидов (`cli seed`)."""

    created: int
    updated: int
    unchanged: int
    deactivated: int
    """Правила сида, которых больше нет в файле: выключены, строки остались для истории."""
    skipped: int
    """В файле, но в БД такое правило завела админка: его не трогаем."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseDecision:
    """Итог решения по кейсу: статус и, если назначена, ступень санкции."""

    case_id: CaseId
    status: CaseStatus
    sanction: SanctionStep | None = None
    restriction_id: RestrictionId | None = None
    """Санкция identity, если ступень что-то запрещает."""


@dataclass(frozen=True, slots=True, kw_only=True)
class QueueSla:
    """SLA очереди (дашборд 6.6): доля решённых в срок и просроченные сейчас."""

    queue: Queue
    decided: int
    decided_in_time: int
    open: int
    overdue: int
    """Открытые, у которых срок уже прошёл."""

    @property
    def in_time_share(self) -> float | None:
        """Доля решённых в срок; None — решённых за период нет."""
        return self.decided_in_time / self.decided if self.decided else None
