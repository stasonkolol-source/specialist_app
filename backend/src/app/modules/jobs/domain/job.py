"""Заявка (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §7.9): агрегат с жизненным циклом.

Создаётся сразу отправленной — «на проверке»: черновик живёт только на клиенте (5.2), поэтому
`draft` в MVP не используется. Модерация публикует заявку или отклоняет; отклонённую клиент
исправляет — снова на проверку. Опубликованная живёт по срочности (§7.9) и продлевается не
больше трёх раз; истёкшую можно переопубликовать. Существенная правка опубликованной (текст,
категория, бюджет) — снова на проверку. Закрывает клиент — с причиной, истекает по сроку
система, снимает модерация. `assigned` и `completed` ведут сделки (6.1a): клиент выбирает отклик —
заявка «в работе», сделку создаёт модуль deals в той же транзакции; отменённая сделка снова
открывает заявку, завершённая — завершает. Каждый переход — в историю статусов (§7.10). Отклики
(5.4) — подагрегат: создаются, правятся и отзываются методами заявки, а лимит мест — её
инвариант (`domain/response.py`).
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.jobs.domain.response import (
    Offer,
    Response,
    ResponseId,
    ResponseReview,
    ResponseStatus,
)
from app.modules.jobs.errors import (
    AlreadyRespondedError,
    InvalidJobError,
    JobExtendLimitError,
    JobFullError,
    JobNotOpenError,
    OfferChangedError,
    OwnJobResponseError,
    ResponseNotActiveError,
    ResponseNotFoundError,
)
from app.platform.contracts.events.jobs import (
    JobClosed,
    JobExpired,
    JobExpiring,
    JobPublished,
    JobSubmitted,
    JobUpdated,
    ResponseDeclined,
    ResponseSubmitted,
    ResponseUpdated,
    ResponseWithdrawn,
)
from app.platform.kernel.aggregate import StatusChange, VersionedAggregate
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.errors import StaleVersionError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId

JobId = NewType("JobId", UUID)

MIN_TITLE: Final = 5
MAX_TITLE: Final = 120
MAX_DESCRIPTION: Final = 3000
MAX_ADDRESS: Final = 300
MAX_EXTENSIONS: Final = 3
REMINDER_LEAD: Final = timedelta(hours=2)
"""За столько до конца срока клиенту — «Заявка закроется через 2 ч» (§11.3, §12)."""
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
CLOSABLE: Final = frozenset(status for status, to in _ALLOWED.items() if JobStatus.CLOSED in to)
"""Из этих статусов заявку можно закрыть: клиентом, удалением или удалением аккаунта."""


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
        for name, value in (
            ("preferred_from", self.preferred_from),
            ("preferred_to", self.preferred_to),
        ):
            if value is not None and value.utcoffset() is None:
                raise InvalidJobError(field=name, reason="timezone_required")
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
    expiry_reminded_at: datetime | None = None
    """Когда напомнили о конце текущего срока; новый срок (публикация, продление) — None."""
    deleted_at: datetime | None = None
    selected_response_id: ResponseId | None = None
    """Выбранный клиентом отклик, пока по нему идёт сделка (6.1a)."""
    revision: int = 1
    """Редакция того, что пишет клиент (`content`): растёт только с его правкой. По ней ETag и
    If-Match правки и решение модератора. `version` растёт с любой записью строки (автопроверка,
    модератор, отклики): по ней правка сразу после автопубликации ловила ложный 412 (ADV-07)."""
    responses: list[Response] = field(default_factory=list)
    """Отклики, кроме удалённых: репозиторий загружает их вместе с заявкой."""
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

    @property
    def can_extend(self) -> bool:
        return self.extensions_count < MAX_EXTENSIONS

    def ensure_revision(self, expected: int | None) -> None:
        """If-Match правки: сверяется редакция содержимого, а не версия строки — переходы
        статуса, которых клиент не делал, его правку не отменяют. None — версию не передали."""
        if expected is not None and expected != self.revision:
            raise StaleVersionError(expected=expected, actual=self.revision)

    def approve(self, *, version: int | None, now: datetime) -> bool:
        """Модерация пропустила: «на проверке» → «опубликована», срок — по срочности. `version` —
        редакция, которую проверяли; другая (клиент успел поправить) или статус — ничего, False."""
        if self.status is not JobStatus.PENDING_MODERATION or self.deleted_at is not None:
            return False
        if version is not None and version != self.revision:
            return False
        first = self.published_at is None
        self._move(JobStatus.PUBLISHED, by=None, kind=ActorKind.MODERATOR, now=now)
        self.published_at = self.published_at or now
        self.expires_at, self.expiry_reminded_at = lifetime(self.content.urgency, now), None
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
            self._closed(CloseReason.REMOVED, now)
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
        if content != self.content:
            self.revision += 1
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
        """Клиент закрыл: с причиной из `CLIENT_CLOSE_REASONS`. Заявку «в работе» закрывает
        отмена её сделки, а не клиент напрямую — иначе сделка осталась бы без заявки."""
        self._ensure_alive()
        if self.status is JobStatus.ASSIGNED:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if reason not in CLIENT_CLOSE_REASONS:
            raise InvalidJobError(field="reason", reason="not_allowed")
        self._move(JobStatus.CLOSED, by=self.client_id, kind=ActorKind.USER, now=now)
        self._closed(reason, now)

    def extend(self, *, now: datetime) -> None:
        """Продлить опубликованную или переопубликовать истёкшую, не больше трёх раз (§7.9).
        Новый срок считается от текущего, если он ещё не вышел: продление «сегодня» вечером
        того же дня не сгорает впустую."""
        self._ensure_alive()
        if self.status not in {JobStatus.PUBLISHED, JobStatus.EXPIRED}:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if not self.can_extend:
            raise JobExtendLimitError(job_id=self.id, limit=MAX_EXTENSIONS)
        republished = self.status is JobStatus.EXPIRED
        self._move(JobStatus.PUBLISHED, by=self.client_id, kind=ActorKind.USER, now=now)
        self.extensions_count += 1
        start = max(now, self.expires_at) if self.expires_at is not None else now
        self.expires_at, self.expiry_reminded_at = lifetime(self.content.urgency, start), None
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
        self._record(
            JobExpired(
                job_id=self.id,
                client_id=self.client_id,
                category_id=self.content.category_id,
                city_id=self.content.place.city_id,
                occurred_at=now,
            )
        )
        return True

    def remind_expiry(self, *, now: datetime) -> bool:
        """До конца срока опубликованной — не больше REMINDER_LEAD: напомнить клиенту один раз
        за срок. Уже напомнили, срок дальше или вышел, другой статус — False."""
        if not self.is_open or self.expires_at is None or self.expiry_reminded_at is not None:
            return False
        if not now < self.expires_at <= now + REMINDER_LEAD:
            return False
        self.expiry_reminded_at = now
        self._record(
            JobExpiring(
                job_id=self.id,
                client_id=self.client_id,
                expires_at=self.expires_at,
                occurred_at=now,
            )
        )
        return True

    def delete(self, *, now: datetime, by_system: bool = False) -> None:
        """Удалить (soft): пропадает из выдачи и списков сразу. Открытая — ещё и закрывается.
        `by_system` — аккаунт удалён (UserDeleted)."""
        if self.deleted_at is not None:
            return
        if self.status is JobStatus.ASSIGNED and not by_system:  # сначала отменить сделку
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if self.status in CLOSABLE:
            kind = ActorKind.SYSTEM if by_system else ActorKind.USER
            by = None if by_system else self.client_id
            self._move(JobStatus.CLOSED, by=by, kind=kind, now=now, reason="deleted")
            self._closed(CloseReason.NOT_NEEDED, now)
        self.deleted_at = now
        self.updated_at = now

    def respond(
        self,
        *,
        response_id: ResponseId,
        performer_id: UserId,
        offer: Offer,
        profile_id: UUID | None = None,
        template_id: UUID | None = None,
        now: datetime,
    ) -> Response:
        """Отклик исполнителя (§7.9): заявка открыта, она не своя, отклика от него ещё нет и
        есть место — иначе 409 со своим кодом. Вызывается под блокировкой строки заявки:
        параллельные отклики не займут больше мест, чем есть."""
        self._ensure_alive()
        if not self.is_open:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if performer_id == self.client_id:
            raise OwnJobResponseError(job_id=self.id)
        if any(response.performer_id == performer_id for response in self.responses):
            raise AlreadyRespondedError(job_id=self.id)
        if self.responses_count >= self.max_responses:
            raise JobFullError(job_id=self.id, limit=self.max_responses)
        first = not self.responses
        response = Response(
            id=response_id,
            performer_id=performer_id,
            status=ResponseStatus.SUBMITTED,
            offer=offer,
            profile_id=profile_id,
            template_id=template_id,
            created_at=now,
            updated_at=now,
            _changed=True,
        )
        self.responses.append(response)
        self.responses_count += 1
        self.updated_at = now
        self._record(
            ResponseSubmitted(
                job_id=self.id,
                response_id=response.id,
                performer_id=performer_id,
                client_id=self.client_id,
                is_first=first,
                published_at=self.published_at,
                category_id=self.content.category_id,
                city_id=self.content.place.city_id,
                occurred_at=now,
            )
        )
        return response

    def revise_response(
        self, response_id: ResponseId, *, performer_id: UserId, offer: Offer, now: datetime
    ) -> Response:
        """Исполнитель поправил свой отклик, пока клиент не решил: текст снова на проверку."""
        response = self._performer_response(response_id, performer_id)
        response.revise(offer, now=now)
        self.updated_at = now
        self._record(
            ResponseUpdated(
                job_id=self.id,
                response_id=response.id,
                performer_id=performer_id,
                occurred_at=now,
            )
        )
        return response

    def withdraw_response(
        self, response_id: ResponseId, *, performer_id: UserId, now: datetime
    ) -> Response:
        """Исполнитель отозвал свой отклик, пока клиент не решил: место освобождается."""
        response = self._performer_response(response_id, performer_id)
        response.withdraw(now=now)
        self.responses_count = max(0, self.responses_count - 1)
        self.updated_at = now
        self._record(
            ResponseWithdrawn(
                job_id=self.id,
                response_id=response.id,
                performer_id=performer_id,
                client_id=self.client_id,
                occurred_at=now,
            )
        )
        return response

    def release_blocked_response(
        self, performer_id: UserId, *, withdrawn: bool, now: datetime
    ) -> bool:
        """Клиент и исполнитель заблокировали друг друга (UserBlocked, MU-3): клиент отклик
        больше не видит и решить по нему не может — активный отклик перестаёт занимать место.
        Заблокированному исполнителю — «не выбран», без события и уведомления; исполнитель,
        который заблокировал сам (`withdrawn`), — «отозван». Активного отклика нет — False."""
        response = next(
            (r for r in self.responses if r.performer_id == performer_id and r.is_active), None
        )
        if response is None:
            return False
        if withdrawn:
            response.withdraw(now=now)
        else:
            response.job_closed(now=now)
        self.responses_count = max(0, self.responses_count - 1)
        self.updated_at = now
        return True

    def clear_response(
        self, response_id: ResponseId, *, revision: int | None, now: datetime
    ) -> bool:
        """Модерация пропустила текст отклика: клиент его видит. Нет отклика, другая редакция
        или уже решено — ничего, False."""
        response = self._find_response(response_id)
        if response is None or not response.clear(revision=revision, now=now):
            return False
        self.updated_at = now
        return True

    def block_response(self, response_id: ResponseId, *, now: datetime) -> bool:
        """Модерация скрыла отклик до исправления: место за ним остаётся — исполнитель правит
        и отправляет снова, второй раз отклик не считается (MU-10). Нет отклика или уже скрыт —
        ничего, False."""
        response = self._find_response(response_id)
        if response is None or not response.block(now=now):
            return False
        self.updated_at = now
        return True

    def accept_response(
        self,
        response_id: ResponseId,
        *,
        client_id: UserId,
        now: datetime,
        revision: int | None = None,
    ) -> Response:
        """Клиент выбрал отклик исполнителем (§7.9): заявка «в работе», остальные активные
        отклики — «не выбран», места свободны. Выбрать можно активный видимый клиенту отклик
        опубликованной заявки; сделку создаёт use case через фасад deals в той же транзакции и
        сам записывает событие ResponseAccepted — в нём id сделки. `revision` — редакция
        предложения, которую клиент видел (If-Match): исполнитель успел поправить — 409
        `offer_changed` с нынешней ценой, а не сделка по цене, которую клиент не видел (ADV-08).
        Без неё — как раньше."""
        response = self._client_response(response_id, client_id)
        if revision is not None and revision != response.revision:
            raise OfferChangedError(
                response_id=response.id,
                revision=response.revision,
                price_type=response.offer.price_type.value,
                price_amount=response.offer.price_amount,
            )
        if self.status is not JobStatus.PUBLISHED:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if not response.is_active:
            raise ResponseNotActiveError(
                response_id=response.id, response_status=response.status.value
            )
        response.accept(now=now)
        for other in self.responses:
            if other is not response:
                other.job_closed(now=now)
        self.responses_count = 0
        self.selected_response_id = response.id
        self._move(JobStatus.ASSIGNED, by=client_id, kind=ActorKind.USER, now=now)
        return response

    def shortlist_response(
        self, response_id: ResponseId, *, client_id: UserId, now: datetime
    ) -> Response:
        """«В избранные» (S24): отклик ждёт решения среди лучших; повтор — без изменений."""
        response = self._client_response(response_id, client_id)
        if self.status is not JobStatus.PUBLISHED:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if not response.is_active:
            raise ResponseNotActiveError(
                response_id=response.id, response_status=response.status.value
            )
        if response.shortlist(now=now):
            self.updated_at = now
        return response

    def decline_response(
        self, response_id: ResponseId, *, client_id: UserId, now: datetime
    ) -> Response:
        """«Отклонить» (S24): место на заявке освобождается."""
        response = self._client_response(response_id, client_id)
        if self.status is not JobStatus.PUBLISHED:
            raise JobNotOpenError(job_id=self.id, job_status=self.status.value)
        if not response.is_active:
            raise ResponseNotActiveError(
                response_id=response.id, response_status=response.status.value
            )
        response.decline(now=now)
        self.responses_count = max(0, self.responses_count - 1)
        self.updated_at = now
        self._record(
            ResponseDeclined(
                job_id=self.id,
                response_id=response.id,
                performer_id=response.performer_id,
                client_id=self.client_id,
                occurred_at=now,
            )
        )
        return response

    def reopen_after_deal(
        self, response_id: ResponseId, *, by_performer: bool, now: datetime
    ) -> bool:
        """Сделку по выбранному отклику отменили (§7.9): заявка снова «опубликована», прежние
        кандидаты («не выбран») — «просмотрен», выбранный — «отозван» исполнителем или
        «отклонён»; места — по активным откликам. Срок вышел, пока шла сделка, — новый срок.
        Заявка уже не «в работе» по этому отклику — ничего, False."""
        if self.status is not JobStatus.ASSIGNED or self.selected_response_id != response_id:
            return False
        chosen = self._find_response(response_id)
        if chosen is not None and chosen.status is ResponseStatus.ACCEPTED:
            chosen.deal_cancelled(by_performer=by_performer, now=now)
        for response in self.responses:
            if (
                response.status is ResponseStatus.NOT_SELECTED
                and response.review is not ResponseReview.BLOCKED
            ):
                response.reconsider(now=now)
        self.responses_count = sum(1 for response in self.responses if response.is_active)
        self.selected_response_id = None
        self._move(
            JobStatus.PUBLISHED, by=None, kind=ActorKind.SYSTEM, now=now, reason="deal_cancelled"
        )
        if self.expires_at is None or self.expires_at <= now:
            self.expires_at, self.expiry_reminded_at = lifetime(self.content.urgency, now), None
        self._publish_event(now, republished=True)
        return True

    def complete_after_deal(self, response_id: ResponseId, *, now: datetime) -> bool:
        """Сделка по выбранному отклику завершена: заявка «завершена» — «нашёлся здесь».
        Заявка уже не «в работе» по этому отклику — ничего, False."""
        if self.status is not JobStatus.ASSIGNED or self.selected_response_id != response_id:
            return False
        self._move(
            JobStatus.COMPLETED, by=None, kind=ActorKind.SYSTEM, now=now, reason="deal_completed"
        )
        self.closed_at, self.close_reason = now, CloseReason.HIRED_HERE
        return True

    def pull_history(self) -> list[tuple[StatusChange[JobStatus], ActorKind]]:
        history, self._history = self._history, []
        return history

    def _find_response(self, response_id: ResponseId) -> Response | None:
        return next((r for r in self.responses if r.id == response_id), None)

    def _client_response(self, response_id: ResponseId, client_id: UserId) -> Response:
        """Отклик на свою заявку, который клиент видит (проверка пройдена); чужая заявка,
        невидимый или удалённый отклик — как несуществующий (404)."""
        self._ensure_alive()
        response = self._find_response(response_id)
        if client_id != self.client_id or response is None or not response.visible_to_client:
            raise ResponseNotFoundError(response_id=response_id)
        return response

    def _performer_response(self, response_id: ResponseId, performer_id: UserId) -> Response:
        """Отклик этого исполнителя; чужой — как несуществующий (404)."""
        response = self._find_response(response_id)
        if response is None or response.performer_id != performer_id:
            raise ResponseNotFoundError(response_id=response_id)
        return response

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
                urgency=self.content.urgency.value,
                republished=republished,
                direct=self.visibility is Visibility.DIRECT,
                occurred_at=now,
            )
        )

    def _closed(self, reason: CloseReason, now: datetime) -> None:
        self.closed_at, self.close_reason = now, reason
        # закрытая заявка решений не ждёт: активные отклики — «не выбран», места свободны
        for response in self.responses:
            response.job_closed(now=now)
        self.responses_count = 0
        self._record(
            JobClosed(
                job_id=self.id,
                client_id=self.client_id,
                category_id=self.content.category_id,
                city_id=self.content.place.city_id,
                reason=reason.value,
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
