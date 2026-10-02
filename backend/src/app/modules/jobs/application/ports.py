"""Порты модуля jobs (ADR-0020 §3, §5): репозиторий заявок, суточная квота и задачи."""

from collections.abc import Sequence
from typing import Final, Protocol

from app.modules.jobs.application.dto import JobView
from app.modules.jobs.domain.job import Job, JobId, JobStatus
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import UserId
from app.platform.queue.port import TaskRef


class JobRepository(Protocol):
    """Агрегат заявки с фото и историей статусов (запись — в активном UoW)."""

    async def add(self, job: Job) -> None: ...

    async def get_for_update(self, job_id: JobId) -> Job:
        """Под блокировкой строки; нет или удалена — JobNotFoundError."""
        ...

    async def save(self, job: Job) -> None: ...

    async def of_client(self, client_id: UserId) -> list[JobId]:
        """Все неудалённые заявки клиента — удаление аккаунта."""
        ...

    async def forget_private(self, client_id: UserId) -> None:
        """Стереть точную точку и адрес во всех заявках клиента, удалённых тоже (§7.10)."""
        ...


class JobQueries(Protocol):
    """Чтение заявок для экранов: без блокировок и UoW."""

    async def view(self, job_id: JobId) -> JobView | None:
        """Заявка целиком (решать, что показать, — политике); удалённой — нет."""
        ...

    async def own(
        self, client_id: UserId, statuses: Sequence[JobStatus], *, limit: int
    ) -> list[JobView]:
        """Заявки клиента в этих статусах, новые первыми; пусто — все статусы."""
        ...

    async def count_active(self, client_id: UserId) -> int:
        """Сколько заявок клиента на проверке или опубликовано — лимит новичка (§13.3)."""
        ...


class JobQuota(Protocol):
    async def take(self, client_id: UserId, *, trusted: bool) -> None:
        """Новая заявка за сутки (§13.3): у уровней 0–1 — пять, у проверенных — двадцать;
        сверх — DailyJobsLimitError (429)."""
        ...


FORGET_CLIENT_JOBS: Final = TaskRef("jobs.forget_client", UserDeleted)
"""Аккаунт удалён — его заявки закрываются и удаляются, адрес стирается (§7.10)."""
