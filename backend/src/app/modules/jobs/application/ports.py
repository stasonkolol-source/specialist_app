"""Порты модуля jobs (ADR-0020 §3, §5): репозиторий заявок, суточная квота и задачи."""

from collections.abc import Sequence
from datetime import datetime
from typing import Final, Protocol

from app.modules.jobs.application.dto import JobView, MyResponseRef
from app.modules.jobs.application.feed import FeedFilters, FeedItem
from app.modules.jobs.application.responses import (
    MyResponse,
    OwnerResponse,
    ResponseGroup,
    TodayQuota,
)
from app.modules.jobs.domain.invite import Invite
from app.modules.jobs.domain.job import Job, JobId, JobStatus
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.domain.template import ResponseTemplate, TemplateId
from app.platform.contracts.events.identity import UserDeleted
from app.platform.contracts.events.jobs import JobPublished
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

    async def job_of_response(self, response_id: ResponseId) -> JobId | None:
        """Заявка отклика; нет такого или удалён — None."""
        ...

    async def performer_jobs(self, performer_id: UserId) -> list[JobId]:
        """Заявки, где у исполнителя есть активный отклик — удаление аккаунта."""
        ...

    async def count_active_responses(self, performer_id: UserId) -> int:
        """Сколько откликов исполнителя ждут решения клиента — квота `active_responses` (v1)."""
        ...

    async def my_responses(
        self, performer_id: UserId, group: ResponseGroup | None, *, page: PageRequest
    ) -> Page[MyResponse]:
        """Отклики исполнителя (S17), новые первыми; группа — чип S17, None — все."""
        ...

    async def performer_response(self, job_id: JobId, performer_id: UserId) -> MyResponseRef | None:
        """Неудалённый отклик исполнителя на заявку — «Вы откликнулись» на S15."""
        ...

    async def my_response(self, performer_id: UserId, response_id: ResponseId) -> MyResponse | None:
        """Отклик исполнителя с заявкой — ответ на отклик, правку и отзыв; чужой — None."""
        ...

    async def my_response_counts(self, performer_id: UserId) -> dict[ResponseGroup, int]:
        """Сколько откликов в каждой группе — числа на чипах S17."""
        ...

    async def unseen_responses(self, job_id: JobId) -> int:
        """Видимые клиенту отклики, которые он ещё не открыл, — «Новых откликов: 3»."""
        ...

    async def job_responses(self, job_id: JobId) -> list[OwnerResponse]:
        """Отклики на заявку для владельца (S23): прошедшие проверку, не отозванные, по
        порядку; `is_first` — самый ранний отклик заявки."""
        ...

    async def is_invited(self, job_id: JobId, performer_id: UserId) -> bool:
        """Исполнителя пригласили в заявку: прямой запрос ему виден (5.6)."""
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


class JobInvites(Protocol):
    """Приглашения в заявку (5.6). Пишутся под блокировкой строки заявки: параллельные
    приглашения не превысят предела."""

    async def of_job(self, job_id: JobId) -> list[Invite]:
        """Приглашённые по порядку приглашения."""
        ...

    async def add(self, invite: Invite) -> None: ...

    async def forget(self, performer_id: UserId) -> None:
        """Удалённый аккаунт исполнителя: его приглашения стираются (§7.10)."""
        ...


class JobViews(Protocol):
    async def count(self, job_id: JobId, viewer_id: UserId) -> None:
        """Просмотр заявки не владельцем (S23 «просмотры»): один человек — не чаще раза в
        сутки. Активный UoW."""
        ...


class ResponseTemplates(Protocol):
    """Шаблоны откликов исполнителя (S57): не больше двух, 0 — основной."""

    async def lock(self, user_id: UserId) -> None:
        """Сериализовать правку шаблонов пользователя до конца транзакции (активный UoW)."""
        ...

    async def of_user(self, user_id: UserId) -> list[ResponseTemplate]:
        """Неудалённые шаблоны по порядку: первый — основной."""
        ...

    async def add(self, template: ResponseTemplate) -> None: ...

    async def save(self, template: ResponseTemplate) -> None: ...

    async def delete(self, template_id: TemplateId, *, now: datetime) -> None: ...

    async def forget(self, user_id: UserId) -> None:
        """Стереть шаблоны пользователя — удаление аккаунта (§7.10)."""
        ...


class ResponseQuota(Protocol):
    async def take(self, performer_id: UserId, *, trusted: bool) -> None:
        """Отклик за сутки (§13.3): у уровней 0–1 — десять, у проверенных — пятьдесят; сверх —
        DailyResponsesLimitError (429)."""
        ...

    async def today(self, performer_id: UserId, *, trusted: bool) -> TodayQuota:
        """Сколько откликов засчитано за сутки и сколько можно — без нового отклика."""
        ...


class JobQuota(Protocol):
    async def take(self, client_id: UserId, *, trusted: bool) -> None:
        """Новая заявка за сутки (§13.3): у уровней 0–1 — пять, у проверенных — двадцать;
        сверх — DailyJobsLimitError (429)."""
        ...


FORGET_CLIENT_JOBS: Final = TaskRef("jobs.forget_client", UserDeleted)
"""Аккаунт удалён — его заявки закрываются и удаляются, адрес стирается (§7.10)."""
WITHDRAW_PERFORMER_RESPONSES: Final = TaskRef("jobs.withdraw_performer_responses", UserDeleted)
"""Аккаунт удалён — его активные отклики отзываются: места на чужих заявках освобождаются."""
ANNOUNCE_DIRECT_REQUEST: Final = TaskRef("jobs.announce_direct_request", JobPublished)
"""Прямой запрос опубликован — приглашённому специалисту JobInvited (5.6)."""
