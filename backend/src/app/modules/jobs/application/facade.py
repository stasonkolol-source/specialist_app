"""Реализация JobsApi (ADR-0020 §6): заявка и отклик для конвейера модерации, публикация и отказ;
краткие сведения о сроке, откликах и приглашении — для уведомлений."""

from typing import Final
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import (
    InviteNotice,
    JobBrief,
    JobForReview,
    JobsApi,
    OwnerResponseView,
    ResponseForReview,
    ResponsesNotice,
    TemplateRef,
)
from app.modules.jobs.application.ports import (
    JobQueries,
    JobRepository,
    ResponsesSeen,
    ResponseTemplates,
)
from app.modules.jobs.domain.job import MAX_EXTENSIONS, Job, JobId, JobStatus
from app.modules.jobs.domain.response import ACTIVE, ResponseId, ResponseReview
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
        catalog: CatalogApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._templates = uow, jobs, queries, templates
        self._seen, self._catalog, self._identity, self._clock = seen, catalog, identity, clock

    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        async with self._uow:
            try:
                job = await self._jobs.get_for_update(JobId(job_id))
            except JobNotFoundError:
                return None
        if job.status not in REVIEWABLE:
            return None
        category = await self._catalog.category(job.content.category_id)
        return JobForReview(
            client_id=job.client_id,
            text=f"{job.content.title}\n\n{job.content.description}".strip(),
            version=job.version,
            media_ids=job.content.media_ids,
            risk_level=int(category.risk_level) if category is not None else 0,
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
