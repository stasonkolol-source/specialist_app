"""DTO модуля moderation (ADR-0020 §6)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.deals.api import DealBrief, DisputeSummary
from app.modules.media.api import MediaRef
from app.modules.moderation.domain.cases import CaseStatus, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportReason, ReportStatus
from app.modules.moderation.domain.sanctions import SanctionStep
from app.platform.ai.port import ContentKind
from app.platform.kernel.ids import CaseId, MediaId, RestrictionId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RecheckImagePayload:
    """Фото без итога проверки (`moderation.recheck_image`): проверить снова или, если ждёт
    слишком долго (`give_up`), отдать модератору."""

    media_id: MediaId
    owner_id: UserId
    purpose: str
    give_up: bool = False


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


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenCaseView:
    """Открытый кейс для `cli moderation-queue` (до чата модераторов 2.5b)."""

    id: CaseId
    queue: Queue
    entity_type: str
    entity_id: UUID
    trigger: str
    status: CaseStatus
    due_at: datetime
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeDossier:
    """Спор модератору (`cli dispute-show`): кейс, спор, сделка и фото обеих сторон."""

    case_id: CaseId
    case_status: CaseStatus
    queue: Queue
    due_at: datetime
    dispute: DisputeSummary
    deal: DealBrief | None
    photos: Mapping[MediaId, MediaRef]
    """Фото по id: адреса — presigned GET приватного бакета на 5 минут."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseFilter:
    """Очередь кейсов в Admin API (2.7b): пустые фильтры — без ограничения."""

    queues: tuple[Queue, ...] = ()
    statuses: tuple[CaseStatus, ...] = ()
    entity_type: EntityType | None = None
    subject_id: UserId | None = None
    """Кейсы о пользователе — история модерации в его карточке."""
    assigned_to: UserId | None = None
    recent_first: bool = False
    """False — по сроку (SLA: ближний первым), True — новые первыми (история)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffCaseView:
    """Кейс персоналу (Admin API): поводы и доказательства как есть, кто взял и кто решил."""

    id: CaseId
    queue: Queue
    entity_type: EntityType
    entity_id: UUID
    subject_id: UserId
    trigger: CaseTrigger
    status: CaseStatus
    opened_at: datetime
    due_at: datetime
    evidence: tuple[Mapping[str, object], ...]
    media_ids: tuple[MediaId, ...]
    appeal_of: CaseId | None
    assigned_to: UserId | None
    decided_by: UserId | None
    reason_code: str | None
    policy_version: str | None
    decided_at: datetime | None
    notes: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportFilter:
    statuses: tuple[ReportStatus, ...] = ()
    target_type: EntityType | None = None
    target_id: UUID | None = None
    case_id: CaseId | None = None
    reporter_id: UserId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffReportView:
    """Жалоба персоналу (Admin API), новые первыми."""

    id: UUID
    reporter_id: UserId
    target_type: EntityType
    target_id: UUID
    reason: ReportReason
    comment: str | None
    is_legal_notice: bool
    case_id: CaseId | None
    status: ReportStatus
    resolution: str | None
    resolved_by: UserId | None
    resolved_at: datetime | None
    created_at: datetime
