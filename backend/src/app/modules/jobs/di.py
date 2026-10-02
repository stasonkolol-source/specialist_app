"""Сборка модуля jobs для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.content import ContentBuilder
from app.modules.jobs.application.facade import JobsFacade
from app.modules.jobs.application.ports import (
    JobHides,
    JobInvites,
    JobQueries,
    JobQuota,
    JobRepository,
    JobViews,
    ResponseQuota,
    ResponsesSeen,
    ResponseTemplates,
    SavedJobs,
)
from app.modules.jobs.application.use_cases.accept_response import AcceptResponse
from app.modules.jobs.application.use_cases.announce_direct_request import AnnounceDirectRequest
from app.modules.jobs.application.use_cases.browse_jobs import BrowseJobs
from app.modules.jobs.application.use_cases.close_job import CloseJob
from app.modules.jobs.application.use_cases.complete_job import CompleteJob
from app.modules.jobs.application.use_cases.count_job_view import CountJobView
from app.modules.jobs.application.use_cases.create_job import CreateJob
from app.modules.jobs.application.use_cases.create_template import CreateTemplate
from app.modules.jobs.application.use_cases.decline_response import DeclineResponse
from app.modules.jobs.application.use_cases.delete_job import DeleteJob
from app.modules.jobs.application.use_cases.delete_template import DeleteTemplate
from app.modules.jobs.application.use_cases.edit_job import EditJob
from app.modules.jobs.application.use_cases.expire_jobs import ExpireJobs
from app.modules.jobs.application.use_cases.extend_job import ExtendJob
from app.modules.jobs.application.use_cases.forget_client_jobs import ForgetClientJobs
from app.modules.jobs.application.use_cases.hide_job import HideJob
from app.modules.jobs.application.use_cases.invite_specialists import InviteSpecialists
from app.modules.jobs.application.use_cases.list_job_invites import ListJobInvites
from app.modules.jobs.application.use_cases.list_job_responses import ListJobResponses
from app.modules.jobs.application.use_cases.list_my_responses import ListMyResponses
from app.modules.jobs.application.use_cases.list_saved_jobs import ListSavedJobs
from app.modules.jobs.application.use_cases.list_templates import ListTemplates
from app.modules.jobs.application.use_cases.remind_expiring_jobs import RemindExpiringJobs
from app.modules.jobs.application.use_cases.reopen_job import ReopenJob
from app.modules.jobs.application.use_cases.respond import Respond
from app.modules.jobs.application.use_cases.respond_with_template import RespondWithTemplate
from app.modules.jobs.application.use_cases.revise_response import ReviseResponse
from app.modules.jobs.application.use_cases.save_job import SaveJob
from app.modules.jobs.application.use_cases.shortlist_response import ShortlistResponse
from app.modules.jobs.application.use_cases.show_job import ShowJob
from app.modules.jobs.application.use_cases.unsave_job import UnsaveJob
from app.modules.jobs.application.use_cases.update_template import UpdateTemplate
from app.modules.jobs.application.use_cases.withdraw_performer_responses import (
    WithdrawPerformerResponses,
)
from app.modules.jobs.application.use_cases.withdraw_response import WithdrawResponse
from app.modules.jobs.infrastructure.hides import SqlJobHides
from app.modules.jobs.infrastructure.invites import SqlJobInvites
from app.modules.jobs.infrastructure.queries import SqlJobQueries
from app.modules.jobs.infrastructure.quota import ValkeyJobQuota, ValkeyResponseQuota
from app.modules.jobs.infrastructure.repositories import SqlJobRepository
from app.modules.jobs.infrastructure.saved import SqlSavedJobs
from app.modules.jobs.infrastructure.templates import SqlResponseTemplates
from app.modules.jobs.infrastructure.views import LimitedJobViews, SqlResponsesSeen


class JobsProvider(Provider):
    """Провайдер модуля jobs: связывает порты с реализациями."""

    scope = Scope.REQUEST

    jobs = provide(SqlJobRepository, provides=JobRepository)
    queries = provide(SqlJobQueries, provides=JobQueries)
    hides = provide(SqlJobHides, provides=JobHides)
    saved = provide(SqlSavedJobs, provides=SavedJobs)
    templates = provide(SqlResponseTemplates, provides=ResponseTemplates)
    invites = provide(SqlJobInvites, provides=JobInvites)
    views = provide(LimitedJobViews, provides=JobViews)
    responses_seen = provide(SqlResponsesSeen, provides=ResponsesSeen)
    quota = provide(ValkeyJobQuota, provides=JobQuota)
    response_quota = provide(ValkeyResponseQuota, provides=ResponseQuota)
    builder = provide(ContentBuilder)
    facade = provide(JobsFacade, provides=JobsApi)
    """Фасад для модерации (адаптер цели `job`) и уведомлений о сроке (5.1)."""
    create_job = provide(CreateJob)
    edit_job = provide(EditJob)
    close_job = provide(CloseJob)
    extend_job = provide(ExtendJob)
    delete_job = provide(DeleteJob)
    forget_client_jobs = provide(ForgetClientJobs)
    expire_jobs = provide(ExpireJobs)
    remind_expiring_jobs = provide(RemindExpiringJobs)
    browse_jobs = provide(BrowseJobs)
    show_job = provide(ShowJob)
    hide_job = provide(HideJob)
    save_job = provide(SaveJob)
    unsave_job = provide(UnsaveJob)
    list_saved_jobs = provide(ListSavedJobs)
    respond = provide(Respond)
    revise_response = provide(ReviseResponse)
    withdraw_response = provide(WithdrawResponse)
    list_my_responses = provide(ListMyResponses)
    list_job_responses = provide(ListJobResponses)
    withdraw_performer_responses = provide(WithdrawPerformerResponses)
    list_templates = provide(ListTemplates)
    create_template = provide(CreateTemplate)
    update_template = provide(UpdateTemplate)
    delete_template = provide(DeleteTemplate)
    respond_with_template = provide(RespondWithTemplate)
    invite_specialists = provide(InviteSpecialists)
    list_job_invites = provide(ListJobInvites)
    announce_direct_request = provide(AnnounceDirectRequest)
    count_job_view = provide(CountJobView)
    accept_response = provide(AcceptResponse)
    shortlist_response = provide(ShortlistResponse)
    decline_response = provide(DeclineResponse)
    reopen_job = provide(ReopenJob)
    complete_job = provide(CompleteJob)
