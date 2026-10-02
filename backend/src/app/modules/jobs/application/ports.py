"""Порты модуля jobs (ADR-0020 §3, §5): репозиторий заявок, суточная квота и задачи."""

from collections.abc import Sequence
from datetime import datetime
from typing import Final, Protocol

from app.modules.jobs.application.dto import JobView
from app.modules.jobs.application.feed import FeedFilters, FeedItem
from app.modules.jobs.domain.job import Job, JobId, JobStatus
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest
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

    async def due_to_expire(self, now: datetime, *, limit: int) -> list[JobId]:
        """Опубликованные, чей срок вышел, — самые давние первыми."""
        ...

    async def expiring(self, now: datetime, until: datetime, *, limit: int) -> list[JobId]:
        """Опубликованные со сроком в (now, until], о котором клиенту ещё не напоминали."""
        ...

    async def count_active(self, client_id: UserId) -> int:
        """Сколько заявок клиента на проверке или опубликовано — лимит новичка (§13.3)."""
        ...

    async def count_published(self, client_id: UserId) -> int:
        """Сколько заявок клиента когда-либо публиковалось — «2 заявки» в блоке клиента S15."""
        ...

    async def feed(
        self,
        filters: FeedFilters,
        *,
        viewer_id: UserId | None,
        page: PageRequest,
        now: datetime,
    ) -> Page[FeedItem]:
        """Лента: свежие сверху, курсор — непрозрачный; свои и скрытые зрителем — не в ней."""
        ...

    async def feed_count(
        self, filters: FeedFilters, *, viewer_id: UserId | None, now: datetime
    ) -> int:
        """Сколько заявок в ленте с этими фильтрами — «Показать N» S14 и счётчик Главной."""
        ...

    async def saved(self, user_id: UserId, *, now: datetime) -> list[FeedItem]:
        """Сохранённые пользователем заявки, которые ещё открыты (опубликованы, публичны, срок
        не вышел), — новые сохранения первыми; без расстояния."""
        ...


class JobHides(Protocol):
    """«Не интересно» (S15): заявка пропадает из ленты этого исполнителя."""

    async def hide(self, user_id: UserId, job_id: JobId) -> None:
        """Повтор ничего не меняет (запись — в активном UoW)."""
        ...

    async def forget(self, user_id: UserId) -> None:
        """Удалить скрытое пользователем — удаление аккаунта (§7.10)."""
        ...


class SavedJobs(Protocol):
    """Сохранённые заявки исполнителя: сердечко S15, сегмент «Задачи» S12."""

    async def save(self, user_id: UserId, job_id: JobId) -> None:
        """Повтор ничего не меняет (запись — в активном UoW)."""
        ...

    async def unsave(self, user_id: UserId, job_id: JobId) -> None:
        """Чего нет — ничего (запись — в активном UoW)."""
        ...

    async def count(self, user_id: UserId) -> int:
        """Сколько сохранено — для лимита."""
        ...

    async def has(self, user_id: UserId, job_id: JobId) -> bool:
        """Уже сохранена — при полном списке повтор не ошибка."""
        ...

    async def forget(self, user_id: UserId) -> None:
        """Удалить сохранённое пользователем — удаление аккаунта (§7.10)."""
        ...


class JobQuota(Protocol):
    async def take(self, client_id: UserId, *, trusted: bool) -> None:
        """Новая заявка за сутки (§13.3): у уровней 0–1 — пять, у проверенных — двадцать;
        сверх — DailyJobsLimitError (429)."""
        ...


FORGET_CLIENT_JOBS: Final = TaskRef("jobs.forget_client", UserDeleted)
"""Аккаунт удалён — его заявки закрываются и удаляются, адрес стирается (§7.10)."""
