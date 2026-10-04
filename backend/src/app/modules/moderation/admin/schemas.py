"""Схемы Admin API moderation (ADR-0020 §10: <Имя>In / <Имя>Out): кейсы, споры, жалобы."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.deals.api import DealBrief, DisputeSummary
from app.modules.media.api import MediaRef
from app.modules.moderation.application.dto import (
    CaseDecision,
    DisputeDossier,
    StaffCaseView,
    StaffReportView,
)
from app.modules.moderation.application.use_cases.resolve_dispute import DisputeResolution
from app.modules.moderation.application.use_cases.try_content_rule import RuleTrial
from app.modules.moderation.domain.cases import MAX_REASON_CODE, CaseStatus, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportReason, ReportStatus
from app.modules.moderation.domain.rules import (
    MAX_PATTERN,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleLanguage,
)
from app.modules.moderation.domain.sanctions import SanctionStep, Severity
from app.platform.kernel.ids import MediaId

MAX_NOTE = 2000


class CaseOut(BaseModel):
    id: UUID
    queue: Queue = Field(
        description="Очередь — она же приоритет: safety — P0, fraud — P1, premod — P2, appeals —"
        " апелляции"
    )
    entity_type: EntityType
    entity_id: UUID
    subject_id: UUID = Field(description="Чей контент или аккаунт: ему — решение и санкция")
    trigger: CaseTrigger
    status: CaseStatus
    opened_at: datetime
    due_at: datetime
    evidence: list[dict[str, Any]] = Field(description="Поводы по порядку: правила, жалобы, …")
    media_ids: list[UUID]
    appeal_of: UUID | None
    assigned_to: UUID | None
    decided_by: UUID | None
    reason_code: str | None
    policy_version: str | None
    decided_at: datetime | None
    notes: str | None

    @classmethod
    def of(cls, case: StaffCaseView) -> CaseOut:
        return cls(
            id=case.id,
            queue=case.queue,
            entity_type=case.entity_type,
            entity_id=case.entity_id,
            subject_id=case.subject_id,
            trigger=case.trigger,
            status=case.status,
            opened_at=case.opened_at,
            due_at=case.due_at,
            evidence=[dict(entry) for entry in case.evidence],
            media_ids=list(case.media_ids),
            appeal_of=case.appeal_of,
            assigned_to=case.assigned_to,
            decided_by=case.decided_by,
            reason_code=case.reason_code,
            policy_version=case.policy_version,
            decided_at=case.decided_at,
            notes=case.notes,
        )


class EscalateIn(BaseModel):
    note: str | None = Field(default=None, max_length=MAX_NOTE, description="Что смутило")


class DecideIn(BaseModel):
    """Решение по обычному кейсу (DecideCase); спор — `resolve-dispute`."""

    verdict: Literal["approved", "rejected"] = Field(
        description="approved — нарушения нет, rejected — нарушение (контент скрывается)"
    )
    reason_code: str | None = Field(
        default=None,
        max_length=MAX_REASON_CODE,
        description="Машинный код причины (`prepayment_scam`, …); при rejected обязателен",
    )
    severity: Severity | None = Field(
        default=None, description="Тяжесть для лестницы санкций; null — без санкции"
    )
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class DecisionOut(BaseModel):
    case_id: UUID
    status: CaseStatus
    sanction: SanctionStep | None
    restriction_id: UUID | None

    @classmethod
    def of(cls, decision: CaseDecision) -> DecisionOut:
        return cls(
            case_id=decision.case_id,
            status=decision.status,
            sanction=decision.sanction,
            restriction_id=decision.restriction_id,
        )


class ResolveDisputeIn(BaseModel):
    """Решение по спору (ResolveDispute): исход сделки и, если нужно, санкция второй стороне."""

    outcome: Literal["completed", "cancelled"] = Field(
        description="completed — работа выполнена, cancelled — сделка отменена модератором"
    )
    reason_code: str = Field(
        min_length=1,
        max_length=MAX_REASON_CODE,
        description="`work_done`, `no_show`, `poor_quality`, `prepayment_scam`, …",
    )
    severity: Severity | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class DisputeResolutionOut(BaseModel):
    case_id: UUID
    dispute_id: UUID
    deal_id: UUID
    outcome: str
    case_status: CaseStatus
    sanction: SanctionStep | None

    @classmethod
    def of(cls, resolved: DisputeResolution) -> DisputeResolutionOut:
        return cls(
            case_id=resolved.case_id,
            dispute_id=resolved.dispute_id,
            deal_id=resolved.deal_id,
            outcome=resolved.outcome,
            case_status=resolved.case_status,
            sanction=resolved.sanction,
        )


class PhotoVariantOut(BaseModel):
    name: str
    url: str = Field(description="presigned GET приватного бакета на 5 минут")
    width: int
    height: int


class EvidencePhotoOut(BaseModel):
    id: UUID
    side: Literal["opener", "respondent"]
    status: str
    variants: list[PhotoVariantOut]

    @classmethod
    def of(cls, ref: MediaRef, side: Literal["opener", "respondent"]) -> EvidencePhotoOut:
        return cls(
            id=ref.id,
            side=side,
            status=ref.status,
            variants=[
                PhotoVariantOut(name=v.name, url=v.url, width=v.width, height=v.height)
                for v in ref.variants
            ],
        )


class DisputeOut(BaseModel):
    id: UUID
    deal_id: UUID
    status: str
    kind: str
    opened_by: UUID
    respondent_id: UUID
    description: str
    respond_by: datetime
    response: str | None
    responded_at: datetime | None
    outcome: str | None
    reason_code: str | None
    created_at: datetime

    @classmethod
    def of(cls, dispute: DisputeSummary) -> DisputeOut:
        return cls(
            id=dispute.id,
            deal_id=dispute.deal_id,
            status=dispute.status,
            kind=dispute.kind,
            opened_by=dispute.opened_by,
            respondent_id=dispute.respondent_id,
            description=dispute.description,
            respond_by=dispute.respond_by,
            response=dispute.response,
            responded_at=dispute.responded_at,
            outcome=dispute.outcome,
            reason_code=dispute.reason_code,
            created_at=dispute.created_at,
        )


class DealOut(BaseModel):
    id: UUID
    client_id: UUID
    performer_id: UUID
    title: str
    status: str
    scheduled_at: datetime | None
    agreed_price: int | None

    @classmethod
    def of(cls, deal: DealBrief) -> DealOut:
        return cls(
            id=deal.id,
            client_id=deal.client_id,
            performer_id=deal.performer_id,
            title=deal.title,
            status=deal.status,
            scheduled_at=deal.scheduled_at,
            agreed_price=deal.agreed_price,
        )


class DisputeDossierOut(BaseModel):
    """Спор модератору: каждый запрос пишет `moderation.dispute.evidence_viewed` в аудит."""

    case_id: UUID
    case_status: CaseStatus
    queue: Queue
    due_at: datetime
    dispute: DisputeOut
    deal: DealOut | None
    photos: list[EvidencePhotoOut]

    @classmethod
    def of(cls, dossier: DisputeDossier) -> DisputeDossierOut:
        dispute = dossier.dispute
        sides: list[tuple[MediaId, Literal["opener", "respondent"]]] = [
            *((media_id, "opener") for media_id in dispute.media_ids),
            *((media_id, "respondent") for media_id in dispute.response_media_ids),
        ]
        return cls(
            case_id=dossier.case_id,
            case_status=dossier.case_status,
            queue=dossier.queue,
            due_at=dossier.due_at,
            dispute=DisputeOut.of(dispute),
            deal=DealOut.of(dossier.deal) if dossier.deal is not None else None,
            photos=[
                EvidencePhotoOut.of(ref, side)
                for media_id, side in sides
                if (ref := dossier.photos.get(media_id)) is not None
            ],
        )


class ReportOut(BaseModel):
    id: UUID
    reporter_id: UUID
    target_type: EntityType
    target_id: UUID
    reason: ReportReason
    comment: str | None
    is_legal_notice: bool
    case_id: UUID | None
    status: ReportStatus
    resolution: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, report: StaffReportView) -> ReportOut:
        return cls(
            id=report.id,
            reporter_id=report.reporter_id,
            target_type=report.target_type,
            target_id=report.target_id,
            reason=report.reason,
            comment=report.comment,
            is_legal_notice=report.is_legal_notice,
            case_id=report.case_id,
            status=report.status,
            resolution=report.resolution,
            resolved_by=report.resolved_by,
            resolved_at=report.resolved_at,
            created_at=report.created_at,
        )


class ContentRuleOut(BaseModel):
    id: int
    kind: RuleKind
    pattern: str
    lang: RuleLanguage | None
    action: RuleAction
    category: RuleCategory
    is_active: bool
    origin: Literal["seed", "admin"] = Field(
        description="seed — строку ведёт `cli seed`, admin — админка (сид её не трогает)"
    )

    @classmethod
    def of(cls, row: Any) -> ContentRuleOut:
        return cls(
            id=row["id"],
            kind=row["kind"],
            pattern=row["pattern"],
            lang=row["lang"],
            action=row["action"],
            category=row["category"],
            is_active=row["is_active"],
            origin=getattr(row["origin"], "value", row["origin"]),
        )


class ContentRuleIn(BaseModel):
    """Правило: регулярка — по скелету текста (латиница в нижнем регистре, без двойных букв), в
    синтаксисе RE2 — без lookaround и обратных ссылок."""

    kind: RuleKind
    pattern: str = Field(min_length=1, max_length=MAX_PATTERN)
    lang: RuleLanguage | None = None
    action: RuleAction
    category: RuleCategory
    is_active: bool = True


class ContentRulePatchIn(BaseModel):
    kind: RuleKind | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=MAX_PATTERN)
    lang: RuleLanguage | None = None
    action: RuleAction | None = None
    category: RuleCategory | None = None
    is_active: bool | None = None


class ContentRuleTrialIn(BaseModel):
    rule_id: int | None = Field(
        default=None, description="Правимая строка: её прежний вариант уходит из «после»"
    )
    kind: RuleKind
    pattern: str = Field(min_length=1, max_length=MAX_PATTERN)
    action: RuleAction
    category: RuleCategory
    sample: str = Field(default="", max_length=4000, description="Текст для пробы")


class RuleMatchOut(BaseModel):
    source: str
    category: str
    action: str
    evidence: str
    rule_id: int | None


class ExampleChangeOut(BaseModel):
    text: str
    expected: str
    before: str
    after: str


class ContentRuleTrialOut(BaseModel):
    error: str | None = Field(description="Почему правило не примут; null — примут")
    skeleton: str
    hit: bool
    matches: list[RuleMatchOut]
    changes: list[ExampleChangeOut] = Field(
        description="Примеры набора, у которых вердикт поменяется"
    )
    examples: int

    @classmethod
    def of(cls, trial: RuleTrial) -> ContentRuleTrialOut:
        return cls(
            error=trial.error,
            skeleton=trial.skeleton,
            hit=trial.hit,
            matches=[
                RuleMatchOut(
                    source=match.source.value,
                    category=match.category.value,
                    action=match.action.value,
                    evidence=match.evidence,
                    rule_id=match.rule_id,
                )
                for match in trial.matches
            ],
            changes=[
                ExampleChangeOut(
                    text=change.text,
                    expected=change.expected,
                    before=change.before,
                    after=change.after,
                )
                for change in trial.changes
            ],
            examples=trial.examples,
        )
