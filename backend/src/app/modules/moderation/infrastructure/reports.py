"""Жалобы в PostgreSQL (ARCHITECTURE §7.3 `moderation.reports`; DEVELOPMENT_PLAN 4.7) и адаптер
«на кого жалоба» — фасады модулей-владельцев объектов."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.messaging.api import MessagingApi
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.reports import Report, ReportReason, ReportStatus
from app.modules.moderation.errors import ReportAlreadyOpenError
from app.modules.moderation.infrastructure.models import OPEN_REPORT, ReportRow
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, UserId

_R = ReportRow.__table__.c


class SqlReportRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def open_of(
        self, reporter_id: UserId, target_type: EntityType, target_id: UUID
    ) -> Report | None:
        row = (
            await self._session.execute(
                select(ReportRow).where(
                    _R.reporter_id == reporter_id,
                    _R.target_type == target_type,
                    _R.target_id == target_id,
                    _R.status == ReportStatus.OPEN,
                )
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def add(self, report: Report) -> None:
        self._uow.require_active()
        self._session.add(
            ReportRow(
                id=report.id,
                reporter_id=report.reporter_id,
                target_type=report.target_type,
                target_id=report.target_id,
                reason=report.reason,
                comment=report.comment,
                case_id=report.case_id,
                status=report.status,
                created_at=report.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, {OPEN_REPORT: ReportAlreadyOpenError})

    async def close_for_case(
        self,
        case_id: CaseId,
        *,
        status: ReportStatus,
        resolved_by: UserId | None,
        resolution: str | None,
        now: datetime,
    ) -> int:
        self._uow.require_active()
        result = await self._session.execute(
            update(ReportRow)
            .where(_R.case_id == case_id, _R.status == ReportStatus.OPEN)
            .values(status=status, resolved_by=resolved_by, resolution=resolution, resolved_at=now)
            .returning(_R.id)
        )
        return len(result.all())

    async def move_to_case(self, case_id: CaseId, successor_id: CaseId) -> int:
        self._uow.require_active()
        result = await self._session.execute(
            update(ReportRow)
            .where(_R.case_id == case_id, _R.status == ReportStatus.OPEN)
            .values(case_id=successor_id)
            .returning(_R.id)
        )
        return len(result.all())


def _to_domain(row: ReportRow) -> Report:
    return Report(
        id=row.id,
        reporter_id=UserId(row.reporter_id),
        target_type=EntityType(row.target_type),
        target_id=row.target_id,
        reason=ReportReason(row.reason),
        comment=row.comment,
        case_id=CaseId(row.case_id) if row.case_id is not None else None,
        status=ReportStatus(row.status),
        created_at=row.created_at,
    )


class FacadeReportTargets:
    """Автор объекта, который видит жалующийся: опубликованный профиль (автор не скрыт
    санкцией), заявка, которую он может открыть, опубликованный отзыв, сообщение его переписки,
    неудалённый аккаунт."""

    def __init__(
        self,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        jobs: JobsApi,
        reviews: ReviewsApi,
        messaging: MessagingApi,
    ) -> None:
        self._identity, self._specialists, self._jobs = identity, specialists, jobs
        self._reviews, self._messaging = reviews, messaging

    async def subject(
        self, target_type: EntityType, target_id: UUID, reporter_id: UserId
    ) -> UserId | None:
        match target_type:
            case EntityType.PROFILE:
                card = (await self._specialists.public_cards([target_id])).get(target_id)
                if card is None or await self._identity.hidden_from_search([card.user_id]):
                    return None
                return card.user_id
            case EntityType.JOB:
                # видимость — как у GET /jobs/{id}: чужой прямой запрос и закрытая — 404
                return await self._jobs.visible_author(target_id, reporter_id)
            case EntityType.REVIEW:
                review = await self._reviews.published_review(target_id)
                return review.author_id if review is not None else None
            case EntityType.MESSAGE:
                return await self._messaging.message_sender(target_id, reporter_id)
            case EntityType.USER:
                user = await self._identity.get_user(UserId(target_id))
                return user.id if user is not None and not user.is_deleted else None
            case _:
                return None

    async def counterpart(self, conversation_id: UUID, reporter_id: UserId) -> UserId | None:
        return await self._messaging.counterpart(conversation_id, reporter_id)
