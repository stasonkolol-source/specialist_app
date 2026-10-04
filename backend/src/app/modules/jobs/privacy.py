"""Сроки хранения и выгрузка данных jobs (ARCHITECTURE §7.10, DEVELOPMENT_PLAN 2.12b).

Правило: заявки и отклики — 24 месяца после закрытия, отклонённые модерацией — 6 месяцев.
Выгрузка: заявки клиента с фото и историей статусов, его скрытые и сохранённые заявки,
отклики и шаблоны исполнителя, приглашения его профиля. Точка и адрес — данные самого клиента:
выгружаются; служебный tsvector — нет.
"""

from uuid import UUID

from sqlalchemy import Select, select

from app.modules.jobs.application.use_cases.purge_expired_jobs import (
    PurgeExpiredJobs,
    PurgeExpiredJobsCommand,
)
from app.modules.jobs.infrastructure.models import (
    HiddenJobRow,
    InviteRow,
    JobMediaRow,
    JobRow,
    ResponseRow,
    ResponseTemplateRow,
    SavedJobRow,
    StatusHistoryRow,
)
from app.platform.privacy.registry import ExportTable, RetentionRun, export_section, retention_rule


@retention_rule(
    "jobs.jobs_and_responses", keep="24 мес. после закрытия; отклонённые модерацией — 6 мес."
)
async def jobs_and_responses(run: RetentionRun) -> int:
    async with run.container() as request:
        purge = await request.get(PurgeExpiredJobs)
        return await purge(PurgeExpiredJobsCommand(now=run.now))


def _jobs(user_id: UUID) -> Select[UUID]:
    return select(JobRow.id).where(JobRow.client_id == user_id)


export_section(
    "jobs",
    ExportTable(
        JobRow, lambda user: JobRow.client_id == user, exclude=frozenset({"search_vector"})
    ),
    ExportTable(JobMediaRow, lambda user: JobMediaRow.job_id.in_(_jobs(user))),
    ExportTable(StatusHistoryRow, lambda user: StatusHistoryRow.job_id.in_(_jobs(user))),
    ExportTable(HiddenJobRow, lambda user: HiddenJobRow.user_id == user),
    ExportTable(SavedJobRow, lambda user: SavedJobRow.user_id == user),
    ExportTable(ResponseRow, lambda user: ResponseRow.performer_id == user),
    ExportTable(ResponseTemplateRow, lambda user: ResponseTemplateRow.user_id == user),
    ExportTable(InviteRow, lambda user: InviteRow.performer_id == user),
)
