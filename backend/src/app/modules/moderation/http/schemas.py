"""Схемы HTTP moderation (ADR-0020 §10: <Имя>In / <Имя>Out): жалоба S46, апелляция S49b."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.moderation.application.use_cases.create_report import FiledReport
from app.modules.moderation.application.use_cases.file_appeal import FiledAppeal
from app.modules.moderation.domain.reports import MAX_COMMENT, ReportReason, ReportStatus
from app.platform.http.fields import CleanText

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
    comment: CleanText | None = Field(
        default=None, max_length=MAX_COMMENT, description="Подробности"
    )
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


AppealRestriction = Literal[
    "limited", "posting_blocked", "responding_blocked", "messaging_blocked", "suspended", "banned"
]


class AppealIn(BaseModel):
    """Что обжаловать: решение (`case_id`) или санкцию с экрана S49b (`restriction`); без обоих —
    последнюю санкцию."""

    case_id: UUID | None = Field(
        default=None, description="Решение модерации (кнопка «Обжаловать» уведомления)"
    )
    restriction: AppealRestriction | None = Field(
        default=None, description="Вид санкции из 403 `restricted` (экран S49b)"
    )


class AppealOut(BaseModel):
    id: UUID
    appeal_of: UUID = Field(description="Обжалованное решение")
    status: Literal["pending", "in_review", "escalated", "approved", "rejected"] = Field(
        description="approved — апелляция удовлетворена (санкция снята), rejected — решение"
        " осталось в силе; остальные — на рассмотрении"
    )
    due_at: datetime = Field(description="Срок ответа: 72 часа с подачи")
    created_at: datetime
    repeated: bool = Field(
        description="true — решение уже обжаловали раньше: это та же апелляция (ответ 200)"
    )

    @classmethod
    def of(cls, filed: FiledAppeal) -> AppealOut:
        appeal = filed.appeal
        if appeal.appeal_of is None:  # FileAppeal открывает только апелляции
            raise ValueError(f"case {appeal.id} is not an appeal")
        return cls(
            id=appeal.id,
            appeal_of=appeal.appeal_of,
            status=appeal.status.value,
            due_at=appeal.due_at,
            created_at=appeal.opened_at,
            repeated=not filed.created,
        )
