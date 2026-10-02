"""Заявка (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §7.9): агрегат с жизненным циклом.

Создаётся сразу отправленной — «на проверке»: черновик живёт только на клиенте (5.2), поэтому
`draft` в MVP не используется. Модерация публикует заявку или отклоняет; отклонённую клиент
исправляет — снова на проверку. Опубликованная живёт по срочности (§7.9) и продлевается не
больше трёх раз; истёкшую можно переопубликовать. Существенная правка опубликованной (текст,
категория, бюджет) — снова на проверку. Закрывает клиент — с причиной, истекает по сроку
система, снимает модерация. `assigned` и `completed` ведут сделки (6.1). Каждый переход — в
историю статусов (§7.10).
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.jobs.errors import (
    InvalidJobError,
    JobExtendLimitError,
    JobNotOpenError,
)
from app.platform.contracts.events.jobs import (
    JobClosed,
    JobExpired,
    JobPublished,
    JobSubmitted,
    JobUpdated,
)
from app.platform.kernel.aggregate import StatusChange, VersionedAggregate
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId

JobId = NewType("JobId", UUID)

MIN_TITLE: Final = 5
MAX_TITLE: Final = 120
MAX_DESCRIPTION: Final = 3000
MAX_ADDRESS: Final = 300
MAX_EXTENSIONS: Final = 3
MAX_PHOTOS: Final = 6
MAX_BUDGET: Final = 1_000_000_000 * 100
"""Миллиард динаров в пара: защита от опечатки в нулях (как у прайса)."""
DEFAULT_MAX_RESPONSES: Final = 5


class JobStatus(StrEnum):
    DRAFT = "draft"
    PENDING_MODERATION = "pending_moderation"
    PUBLISHED = "published"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    CLOSED = "closed"
    EXPIRED = "expired"
    REJECTED = "rejected"
    REMOVED = "removed"


class Visibility(StrEnum):
    PUBLIC = "public"
    DIRECT = "direct"
    """Прямой запрос конкретным специалистам (5.6)."""


class Urgency(StrEnum):
    ASAP = "asap"
    TODAY = "today"
    THIS_WEEK = "this_week"
    FLEXIBLE = "flexible"


class BudgetType(StrEnum):
    FIXED = "fixed"
    RANGE = "range"
    NEGOTIABLE = "negotiable"


class BudgetUnit(StrEnum):
    WORK = "work"
    HOUR = "hour"
    M2 = "m2"
    VISIT = "visit"
    ITEM = "item"
    LESSON = "lesson"


class CloseReason(StrEnum):
    HIRED_HERE = "hired_here"
    HIRED_ELSEWHERE = "hired_elsewhere"
    NOT_NEEDED = "not_needed"
    NO_SUITABLE = "no_suitable"
    EXPIRED = "expired"
    REMOVED = "removed"


CLIENT_CLOSE_REASONS: Final = frozenset(
    {
        CloseReason.HIRED_HERE,
        CloseReason.HIRED_ELSEWHERE,
        CloseReason.NOT_NEEDED,
        CloseReason.NO_SUITABLE,
    }
)
"""Причины, которые выбирает клиент; `expired` и `removed` ставят срок и модерация."""

ACTIVE: Final = frozenset({JobStatus.PENDING_MODERATION, JobStatus.PUBLISHED})
"""Активные заявки — для лимита «3 активные» новичка (§13.3)."""
EDITABLE: Final = frozenset(
    {JobStatus.PENDING_MODERATION, JobStatus.PUBLISHED, JobStatus.REJECTED, JobStatus.EXPIRED}
)

_ALLOWED: Final[dict[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.DRAFT: frozenset({JobStatus.PENDING_MODERATION}),
    JobStatus.PENDING_MODERATION: frozenset(
        {JobStatus.PUBLISHED, JobStatus.REJECTED, JobStatus.CLOSED}
    ),
    JobStatus.REJECTED: frozenset({JobStatus.PENDING_MODERATION, JobStatus.CLOSED}),
    JobStatus.PUBLISHED: frozenset(
        {
            JobStatus.PUBLISHED,
            JobStatus.PENDING_MODERATION,
            JobStatus.ASSIGNED,
            JobStatus.CLOSED,
            JobStatus.EXPIRED,
            JobStatus.REMOVED,
        }
    ),
    JobStatus.EXPIRED: frozenset(
        {JobStatus.PUBLISHED, JobStatus.PENDING_MODERATION, JobStatus.CLOSED}
    ),
    JobStatus.ASSIGNED: frozenset({JobStatus.COMPLETED, JobStatus.PUBLISHED, JobStatus.CLOSED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CLOSED: frozenset(),
    JobStatus.REMOVED: frozenset(),
}


class ActorKind(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True, kw_only=True)
class Budget:
    """Бюджет в пара: `fixed` — min, `range` — min…max, `negotiable` — без сумм."""

    type: BudgetType
    min: int | None = None
    max: int | None = None
    unit: BudgetUnit = BudgetUnit.WORK

    def __post_init__(self) -> None:
        amounts = [amount for amount in (self.min, self.max) if amount is not None]
        if any(amount <= 0 or amount > MAX_BUDGET for amount in amounts):
            raise InvalidJobError(field="budget", reason="out_of_range")
        if self.type is BudgetType.NEGOTIABLE:
            if amounts:
                raise InvalidJobError(field="budget", reason="negotiable_has_amount")
            return
        if self.min is None:
            raise InvalidJobError(field="budget_min", reason="required")
        if self.type is BudgetType.FIXED and self.max is not None:
            raise InvalidJobError(field="budget_max", reason="fixed_has_max")
        if self.max is not None and self.max < self.min:
            raise InvalidJobError(field="budget_max", reason="below_min")


@dataclass(frozen=True, slots=True, kw_only=True)
class Place:
    """Где: город, район, точка. Точная точка и адрес — только выбранному исполнителю (§7.6);
    наружу — смещённая точка и район."""

    city_id: CityId
    district_id: DistrictId | None = None
    point_exact: GeoPoint | None = None
    point_public: GeoPoint | None = None
    address_private: str | None = None

    def __post_init__(self) -> None:
        if self.address_private is not None and len(self.address_private) > MAX_ADDRESS:
            raise InvalidJobError(field="address_private", reason="too_long")


@dataclass(frozen=True, slots=True, kw_only=True)
class JobContent:
    """Что клиент пишет и выбирает: текст, услуга, срочность, бюджет, место, фото."""

    title: str
    description: str
    category_id: CategoryId
    category_path: tuple[CategoryId, ...]
    urgency: Urgency
    budget: Budget
    place: Place
    content_lang: str
    preferred_from: datetime | None = None
    preferred_to: datetime | None = None
    languages: tuple[str, ...] = ()
    media_ids: tuple[MediaId, ...] = ()

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not MIN_TITLE <= len(title) <= MAX_TITLE:
            raise InvalidJobError(field="title", reason="length")
        if len(self.description) > MAX_DESCRIPTION:
            raise InvalidJobError(field="description", reason="too_long")
        if len(self.media_ids) > MAX_PHOTOS:
            raise InvalidJobError(field="media_ids", reason="too_many")
        if (
            self.preferred_from is not None
            and self.preferred_to is not None
            and self.preferred_to < self.preferred_from
        ):
            raise InvalidJobError(field="preferred_to", reason="before_from")
        if title != self.title:
            object.__setattr__(self, "title", title)

    def substantive_change(self, other: JobContent) -> bool:
        """Правка, после которой опубликованную заявку снова проверяет модерация: текст,
        услуга, бюджет или фото. Срочность, даты, район и языки — без проверки."""
        return (
            self.title != other.title
            or self.description != other.description
            or self.category_id != other.category_id
            or self.budget != other.budget
            or self.media_ids != other.media_ids
        )


def lifetime(urgency: Urgency, now: datetime) -> datetime:
    """Срок жизни опубликованной заявки (§7.9): «срочно» — сутки, «сегодня» — до конца дня
    по Белграду и ещё 6 часов, «на неделе» — 7 дней, «не срочно» — 30 дней."""
    if urgency is Urgency.ASAP:
        return now + timedelta(hours=24)
    if urgency is Urgency.TODAY:
        local = now.astimezone(BUSINESS_TZ)
        end_of_day = datetime.combine(local.date(), time(23, 59), tzinfo=BUSINESS_TZ)
        return end_of_day + timedelta(hours=6)
    if urgency is Urgency.THIS_WEEK:
        return now + timedelta(days=7)
    return now + timedelta(days=30)


@dataclass(eq=False, kw_only=True)
class Job(VersionedAggregate):
    id: JobId
    client_id: UserId
    content: JobContent
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    visibility: Visibility = Visibility.PUBLIC
    source: str = "tma"
    max_responses: int = DEFAULT_MAX_RESPONSES
    responses_count: int = 0
    extensions_count: int = 0
    published_at: datetime | None = None
    expires_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
    moderation_note: str | None = None
    deleted_at: datetime | None = None
    _history: list[tuple[StatusChange[JobStatus], ActorKind]] = field(
        default_factory=list, init=False, repr=False
    )

    @classmethod
    def submit(
        cls,
        *,
        job_id: JobId,
        client_id: UserId,
        content: JobContent,
        max_responses: int,
        visibility: Visibility = Visibility.PUBLIC,
        source: str = "tma",
        now: datetime,
    ) -> Job:
        """Новая заявка — сразу на проверку (POST /jobs без черновика, отклонение от §8.5)."""
        job = cls(
            id=job_id,
            client_id=client_id,
            content=content,
            status=JobStatus.DRAFT,
            created_at=now,
            updated_at=now,
            visibility=visibility,
            source=source,
            max_responses=max_responses,
            version=1,
        )
        job._move(JobStatus.PENDING_MODERATION, by=client_id, kind=ActorKind.USER, now=now)
        job._record(JobSubmitted(job_id=job.id, client_id=client_id, occurred_at=now))
        return job

    @property
    def is_open(self) -> bool:
        """Принимает отклики: опубликована и не удалена."""
        return self.status is JobStatus.PUBLISHED and self.deleted_at is None

    def approve(self, *, version: int | None, now: datetime) -> bool:
        """Модерация пропустила: «на проверке» → «опубликована», срок — по срочности. Другая
        версия (клиент успел поправить) или статус — ничего, False."""
        if self.status is not JobStatus.PENDING_MODERATION or self.deleted_at is not None:
            return False
        if version is not None and version != self.version:
            return False
        first = self.published_at is None
        self._move(JobStatus.PUBLISHED, by=None, kind=ActorKind.MODERATOR, now=now)
        self.published_at = self.published_at or now
        self.expires_at = lifetime(self.content.urgency, now)
        self.moderation_note = None
        self._publish_event(now, republished=not first)
        return True

    def reject(self, *, reason_code: str, now: datetime) -> bool:
        """Модерация отклонила: ждавшая проверки — «отклонена» (клиент исправит), опубликованная
        — «снята». Остальное — ничего, False."""
        if self.deleted_at is not None:
            return False
        if self.status is JobStatus.PENDING_MODERATION:
            target = JobStatus.REJECTED
        elif self.status is JobStatus.PUBLISHED:
            target = JobStatus.REMOVED
        else:
            return False
        self._move(target, by=None, kind=ActorKind.MODERATOR, now=now, reason=reason_code)
        self.moderation_note = reason_code
        if target is JobStatus.REMOVED:
            self.closed_at, self.close_reason = now, CloseReason.REMOVED
            self._record(
                JobClosed(
                    job_id=self.id,
                    client_id=self.client_id,
                    reason=CloseReason.REMOVED.value,
                    occurred_at=now,
                )
            )
        return True

    def edit(self, content: JobContent, *, now: datetime) -> bool:
        """Правка владельцем. Отклонённая — снова на проверку; существенная правка
        опубликованной или истёкшей — тоже. True — заявку снова проверяет модерация."""
        self._ensure_alive()
        if self.status not in EDITABLE:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        review = self.status is JobStatus.REJECTED or (
            self.status in {JobStatus.PUBLISHED, JobStatus.EXPIRED}
            and content.substantive_change(self.content)
        )
        self.content = content
        self.updated_at = now
        if review:
            self._move(
                JobStatus.PENDING_MODERATION, by=self.client_id, kind=ActorKind.USER, now=now
            )
            self.moderation_note = None
        self._record(JobUpdated(job_id=self.id, client_id=self.client_id, occurred_at=now))
        return review or self.status is JobStatus.PENDING_MODERATION

    def close(self, reason: CloseReason, *, now: datetime) -> None:
        """Клиент закрыл: с причиной из `CLIENT_CLOSE_REASONS`."""
        self._ensure_alive()
        if reason not in CLIENT_CLOSE_REASONS:
            raise InvalidJobError(field="reason", reason="not_allowed")
        self._move(JobStatus.CLOSED, by=self.client_id, kind=ActorKind.USER, now=now)
        self.closed_at, self.close_reason = now, reason
        self._record(
            JobClosed(
                job_id=self.id, client_id=self.client_id, reason=reason.value, occurred_at=now
            )
        )

    def extend(self, *, now: datetime) -> None:
        """Продлить опубликованную или переопубликовать истёкшую, не больше трёх раз (§7.9).
        Новый срок считается от текущего, если он ещё не вышел: продление «сегодня» вечером
        того же дня не сгорает впустую."""
        self._ensure_alive()
        if self.status not in {JobStatus.PUBLISHED, JobStatus.EXPIRED}:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if self.extensions_count >= MAX_EXTENSIONS:
            raise JobExtendLimitError(job_id=self.id, limit=MAX_EXTENSIONS)
        republished = self.status is JobStatus.EXPIRED
        self._move(JobStatus.PUBLISHED, by=self.client_id, kind=ActorKind.USER, now=now)
        self.extensions_count += 1
        start = max(now, self.expires_at) if self.expires_at is not None else now
        self.expires_at = lifetime(self.content.urgency, start)
        self.updated_at = now
        if republished:
            self._publish_event(now, republished=True)
        else:
            self._record(JobUpdated(job_id=self.id, client_id=self.client_id, occurred_at=now))

    def expire(self, *, now: datetime) -> bool:
        """Срок вышел: «опубликована» → «истекла». Ещё не вышел или другой статус — False."""
        if self.status is not JobStatus.PUBLISHED or self.expires_at is None:
            return False
        if self.expires_at > now or self.deleted_at is not None:
            return False
        self._move(JobStatus.EXPIRED, by=None, kind=ActorKind.SYSTEM, now=now)
        self._record(JobExpired(job_id=self.id, client_id=self.client_id, occurred_at=now))
        return True

    def delete(self, *, now: datetime, by_system: bool = False) -> None:
        """Удалить (soft): пропадает из выдачи и списков сразу. Открытая — ещё и закрывается.
        `by_system` — аккаунт удалён (UserDeleted)."""
        if self.deleted_at is not None:
            return
        if self.status in _ALLOWED and JobStatus.CLOSED in _ALLOWED[self.status]:
            kind = ActorKind.SYSTEM if by_system else ActorKind.USER
            by = None if by_system else self.client_id
            self._move(JobStatus.CLOSED, by=by, kind=kind, now=now, reason="deleted")
            self.closed_at, self.close_reason = now, CloseReason.NOT_NEEDED
            self._record(
                JobClosed(
                    job_id=self.id,
                    client_id=self.client_id,
                    reason=CloseReason.NOT_NEEDED.value,
                    occurred_at=now,
                )
            )
        self.deleted_at = now
        self.updated_at = now

    def pull_history(self) -> list[tuple[StatusChange[JobStatus], ActorKind]]:
        history, self._history = self._history, []
        return history

    def _ensure_alive(self) -> None:
        if self.deleted_at is not None:
            raise JobNotOpenError(job_id=self.id, job_status="deleted")

    def _publish_event(self, now: datetime, *, republished: bool) -> None:
        self._record(
            JobPublished(
                job_id=self.id,
                client_id=self.client_id,
                category_id=self.content.category_id,
                city_id=self.content.place.city_id,
                republished=republished,
                occurred_at=now,
            )
        )

    def _move(
        self,
        target: JobStatus,
        *,
        by: UserId | None,
        kind: ActorKind,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        if target not in _ALLOWED[self.status]:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        self._history.append(
            (StatusChange(from_=self.status, to=target, actor_id=by, reason=reason, at=now), kind)
        )
        self.status = target
        self.updated_at = now
