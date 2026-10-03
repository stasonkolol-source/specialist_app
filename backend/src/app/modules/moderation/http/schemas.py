"""Схемы HTTP moderation (ADR-0020 §10: <Имя>In / <Имя>Out): жалоба S46."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.moderation.application.use_cases.create_report import FiledReport
from app.modules.moderation.domain.reports import MAX_COMMENT, ReportReason, ReportStatus

ReportTargetType = Literal["profile", "job", "review", "message", "user"]


class ReportIn(BaseModel):
    """Жалоба: на что, причина из списка своего типа, подробности по желанию."""

    target_type: ReportTargetType = Field(
        description="Профиль специалиста (S08), заявка (S15), отзыв (S11), сообщение или"
        " собеседник (меню чата S30)"
    )
    target_id: UUID
    reason: ReportReason = Field(
        description="profile: fraud, fake_profile, offensive, prohibited, other; job: fraud,"
        " prohibited, spam, offensive, other; review: defamation, offensive, personal_data, spam,"
        " other; message: fraud, offensive, spam, personal_data, other; user: fraud, offensive,"
        " no_show, spam, fake_profile, other"
    )
    comment: str | None = Field(default=None, max_length=MAX_COMMENT, description="Подробности")
    conversation_id: UUID | None = Field(
        default=None, description="Диалог, где всё случилось (жалоба на собеседника из S30)"
    )


class ReportOut(BaseModel):
    id: UUID
    target_type: ReportTargetType
    target_id: UUID
    reason: ReportReason
    status: ReportStatus
    queue: Literal["safety", "fraud"] = Field(
        description="safety — P0, модератор в течение часа; fraud — P1, в течение 2 часов"
        " (с 08:00 до 23:00)"
    )
    created_at: datetime

    @classmethod
    def of(cls, filed: FiledReport) -> ReportOut:
        report = filed.report
        return cls(
            id=report.id,
            target_type=report.target_type.value,  # type: ignore[arg-type]  # из ReportIn
            target_id=report.target_id,
            reason=report.reason,
            status=report.status,
            queue=filed.queue.value,  # type: ignore[arg-type]  # report_queue: safety | fraud
            created_at=report.created_at,
        )
