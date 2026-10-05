"""Реализация JobsApi (ADR-0020 §6): заявка и отклик для конвейера модерации, публикация и отказ;
краткие сведения о сроке, откликах, приглашении и подписках (карточка B1, подборка) — для
уведомлений."""

from collections.abc import Collection, Mapping
from typing import Final
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import (
    ChatResponse,
    ClosedNotice,
    DealJob,
    DigestLine,
    InviteNotice,
    JobBrief,
    JobForReview,
    JobsApi,
    MatchNotice,
    OwnerResponseView,
    PublicJob,
    ResponseForReview,
    ResponsesNotice,
    TemplateRef,
)
from app.modules.jobs.application.ports import (
    JobAlerts,
    JobQueries,
    JobRepository,
    ResponsesSeen,
    ResponseTemplates,
)
from app.modules.jobs.application.visibility import visible_to
from app.modules.jobs.domain.alert import AlertId
from app.modules.jobs.domain.job import MAX_EXTENSIONS, Job, JobId, JobStatus, Visibility
from app.modules.jobs.domain.response import ACTIVE, ResponseId, ResponseReview, ResponseStatus
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

REVIEWABLE: Final = frozenset({JobStatus.PENDING_MODERATION, JobStatus.PUBLISHED})


class JobsFacade(JobsApi):
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        templates: ResponseTemplates,
        seen: ResponsesSeen,
        alerts: JobAlerts,
        catalog: CatalogApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._templates = uow, jobs, queries, templates
        self._seen, self._alerts = seen, alerts
        self._catalog, self._identity, self._clock = catalog, identity, clock

    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        async with self._uow:
            try:
                job = await self._jobs.get_for_update(JobId(job_id))
            except JobNotFoundError:
                return None
        if job.status not in REVIEWABLE:
            return None
        category = await self._catalog.category(job.content.category_id)
        content = job.content
        return JobForReview(
            client_id=job.client_id,
            text=f"{content.title}\n\n{content.description}".strip(),
            version=job.version,
            media_ids=content.media_ids,
            risk_level=int(category.risk_level) if category is not None else 0,
            title=content.title,
            description=content.description,
            budget_type=content.budget.type.value,
            budget_min=content.budget.min,
            budget_max=content.budget.max,
            budget_unit=content.budget.unit.value,
            district_id=content.place.district_id,
        )

    async def approve_job(self, job_id: UUID, *, version: int | None) -> None:
        self._uow.require_active()
        try:
            job = await self._jobs.get_for_update(JobId(job_id))
        except JobNotFoundError:
            return
        if job.approve(version=version, now=self._clock.now()):
            await self._jobs.save(job)

    async def reject_job(self, job_id: UUID, *, reason_code: str) -> None:
        self._uow.require_active()
        try:
            job = await self._jobs.get_for_update(JobId(job_id))
        except JobNotFoundError:
            return
        if job.reject(reason_code=reason_code, now=self._clock.now()):
            await self._jobs.save(job)

    async def job_brief(self, job_id: UUID) -> JobBrief | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        return JobBrief(
            client_id=job.client_id,
            title=job.title,
            status=job.status.value,
            expires_at=job.expires_at,
            can_extend=job.extensions_count < MAX_EXTENSIONS,
        )

    async def public_job(self, job_id: UUID) -> PublicJob | None:
        job = await self._queries.view(JobId(job_id))
        if job is None or not await visible_to(self._queries, job, None):
            return None
        return PublicJob(
            client_id=job.client_id,
            title=job.title,
            city_id=job.city_id,
            district_id=job.district_id,
            budget_type=job.budget_type.value,
            budget_min=job.budget_min,
            budget_max=job.budget_max,
            budget_unit=job.budget_unit.value,
            urgency=job.urgency.value,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
        )

    async def responses_notice(self, job_id: UUID) -> ResponsesNotice | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        return ResponsesNotice(
            client_id=job.client_id,
            title=job.title,
            status=job.status.value,
            unseen=await self._queries.unseen_responses(JobId(job_id)),
        )

    async def job_titles(self, job_ids: Collection[UUID]) -> dict[UUID, str]:
        titles = await self._queries.titles([JobId(job_id) for job_id in job_ids])
        return {UUID(str(job_id)): title for job_id, title in titles.items()}

    async def unseen_responses(self, client_id: UserId) -> int:
        return await self._queries.unseen_total(client_id)

    async def response_job(self, response_id: UUID) -> UUID | None:
        return await self._queries.job_of_response(ResponseId(response_id))

    async def owner_responses(self, job_id: UUID, owner_id: UserId) -> list[OwnerResponseView]:
        job = await self._queries.view(JobId(job_id))
        if job is None or job.client_id != owner_id:
            raise JobNotFoundError(job_id=job_id)
        seen = job.responses_seen_at
        return [
            OwnerResponseView(
                id=response.id,
                performer_id=response.performer_id,
                profile_id=response.profile_id,
                status=response.status.value,
                message=response.offer.message,
                price_type=response.offer.price_type.value,
                price_amount=response.offer.price_amount,
                availability_note=response.offer.availability_note,
                is_first=response.is_first,
                is_new=response.status in ACTIVE and (seen is None or response.updated_at > seen),
                created_at=response.created_at,
            )
            for response in await self._queries.job_responses(job.id)
        ]

    async def see_responses(self, job_id: UUID) -> None:
        self._uow.require_active()
        await self._seen.mark(JobId(job_id), self._clock.now())

    async def chat_response(self, response_id: UUID) -> ChatResponse | None:
        job = await self._job_of_response(ResponseId(response_id))
        response = next((r for r in job.responses if r.id == response_id), None) if job else None
        if job is None or response is None:
            return None
        offer = response.offer
        return ChatResponse(
            id=response.id,
            job_id=job.id,
            client_id=job.client_id,
            performer_id=response.performer_id,
            status=response.status.value,
            visible_to_client=response.visible_to_client,
            message=offer.message,
            price_type=offer.price_type.value,
            price_amount=offer.price_amount,
            availability_note=offer.availability_note,
            created_at=response.created_at,
        )

    async def deal_job(
        self, job_id: UUID, response_id: UUID | None, viewer_id: UserId
    ) -> DealJob | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        response = None
        if response_id is not None:
            found = await self._queries.deal_response(ResponseId(response_id))
            response = found if found is not None and found.job_id == job.id else None
        chosen = (
            response is not None
            and response.performer_id == viewer_id
            and response.status is ResponseStatus.ACCEPTED
        )
        exact = viewer_id == job.client_id or chosen
        return DealJob(
            title=job.title,
            city_id=job.city_id,
            district_id=job.district_id,
            urgency=job.urgency.value,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
            budget_min=job.budget_min,
            budget_max=job.budget_max,
            address=job.address_private if exact else None,
            point=job.point_exact if exact else None,
            responded_at=response.created_at if response is not None else None,
            availability_note=response.availability_note if response is not None else None,
        )

    async def passed_over(self, job_id: UUID) -> list[UserId]:
        return await self._queries.passed_over(JobId(job_id))

    async def closed_notice(self, job_id: UUID) -> ClosedNotice | None:
        closed = await self._queries.closed_with(JobId(job_id))
        if closed is None:
            return None
        title, performers = closed
        return ClosedNotice(title=title, performer_ids=tuple(performers))

    async def invite_notice(self, job_id: UUID, performer_id: UserId) -> InviteNotice | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        client = await self._identity.get_user(job.client_id)
        responded = await self._queries.performer_response(job.id, performer_id) is not None
        templates = () if responded else await self._templates.of_user(performer_id)
        return InviteNotice(
            title=job.title,
            status=job.status.value,
            client_name=client.display_name if client and not client.is_deleted else None,
            templates=tuple(TemplateRef(id=item.id, title=item.title) for item in templates),
        )

    async def match_notice(
        self, job_id: UUID, user_id: UserId, alert_id: UUID
    ) -> MatchNotice | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        now = self._clock.now()
        alert = await self._alerts.get(AlertId(alert_id))
        opened = await self._queries.still_open([job.id], now)
        skipped = await self._queries.skipped([job.id], user_id)
        templates = () if skipped else await self._templates.of_user(user_id)
        return MatchNotice(
            title=job.title,
            open=job.id in opened and job.visibility is Visibility.PUBLIC,
            budget_type=job.budget_type.value,
            budget_min=job.budget_min,
            budget_max=job.budget_max,
            budget_unit=job.budget_unit.value,
            district_id=job.district_id,
            urgency=job.urgency.value,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
            responses_count=job.responses_count,
            max_responses=job.max_responses,
            expires_at=job.expires_at,
            alert_category_ids=alert.criteria.category_ids if alert is not None else (),
            alert_receives=(alert is not None and alert.user_id == user_id and alert.receives(now)),
            skipped=bool(skipped),
            templates=tuple(TemplateRef(id=item.id, title=item.title) for item in templates),
        )

    async def digest_lines(
        self, user_id: UserId, alerts: Mapping[UUID, Collection[UUID]]
    ) -> list[DigestLine]:
        now = self._clock.now()
        mine = {alert.id: alert for alert in await self._alerts.of_user(user_id)}
        wanted = {JobId(job_id) for job_ids in alerts.values() for job_id in job_ids}
        opened = await self._queries.still_open(wanted, now)
        opened -= await self._queries.skipped(opened, user_id)
        lines = []
        for alert_id, job_ids in alerts.items():
            alert = mine.get(AlertId(alert_id))
            if alert is None or not alert.receives(now):
                continue
            lines.append(
                DigestLine(
                    alert_id=alert.id,
                    category_ids=alert.criteria.category_ids,
                    open_jobs=sum(1 for job_id in set(job_ids) if JobId(job_id) in opened),
                )
            )
        return lines

    async def response_for_review(self, response_id: UUID) -> ResponseForReview | None:
        job = await self._job_of_response(ResponseId(response_id))
        response = next((r for r in job.responses if r.id == response_id), None) if job else None
        if response is None or response.review is not ResponseReview.PENDING:
            return None
        offer = response.offer
        text = "\n\n".join(part for part in (offer.message, offer.availability_note) if part)
        return ResponseForReview(
            performer_id=response.performer_id, text=text, revision=response.revision
        )

    async def approve_response(self, response_id: UUID, *, version: int | None) -> None:
        self._uow.require_active()
        job = await self._job_for_update(ResponseId(response_id))
        if job is not None and job.clear_response(
            ResponseId(response_id), revision=version, now=self._clock.now()
        ):
            await self._jobs.save(job)

    async def reject_response(
        self,
        response_id: UUID,
        *,
        reason_code: str,  # noqa: ARG002 — причина остаётся в деле модерации
    ) -> None:
        self._uow.require_active()
        job = await self._job_for_update(ResponseId(response_id))
        if job is not None and job.block_response(ResponseId(response_id), now=self._clock.now()):
            await self._jobs.save(job)

    async def _job_of_response(self, response_id: ResponseId) -> Job | None:
        """Заявка отклика целиком — в своей транзакции (конвейер читает до своей)."""
        async with self._uow:
            return await self._job_for_update(response_id)

    async def _job_for_update(self, response_id: ResponseId) -> Job | None:
        job_id = await self._queries.job_of_response(response_id)
        if job_id is None:
            return None
        try:
            return await self._jobs.get_for_update(job_id)
        except JobNotFoundError:
            return None
