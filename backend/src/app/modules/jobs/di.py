"""Сборка модуля jobs для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.content import ContentBuilder
from app.modules.jobs.application.facade import JobsFacade
from app.modules.jobs.application.ports import JobQueries, JobQuota, JobRepository
from app.modules.jobs.application.use_cases.close_job import CloseJob
from app.modules.jobs.application.use_cases.create_job import CreateJob
from app.modules.jobs.application.use_cases.delete_job import DeleteJob
from app.modules.jobs.application.use_cases.edit_job import EditJob
from app.modules.jobs.application.use_cases.expire_jobs import ExpireJobs
from app.modules.jobs.application.use_cases.extend_job import ExtendJob
from app.modules.jobs.application.use_cases.forget_client_jobs import ForgetClientJobs
from app.modules.jobs.application.use_cases.remind_expiring_jobs import RemindExpiringJobs
from app.modules.jobs.infrastructure.queries import SqlJobQueries
from app.modules.jobs.infrastructure.quota import ValkeyJobQuota
from app.modules.jobs.infrastructure.repositories import SqlJobRepository


class JobsProvider(Provider):
    """Провайдер модуля jobs: связывает порты с реализациями."""

    scope = Scope.REQUEST

    jobs = provide(SqlJobRepository, provides=JobRepository)
    queries = provide(SqlJobQueries, provides=JobQueries)
    quota = provide(ValkeyJobQuota, provides=JobQuota)
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
