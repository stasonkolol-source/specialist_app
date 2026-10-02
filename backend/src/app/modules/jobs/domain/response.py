"""Отклик (DEVELOPMENT_PLAN 5.4; ARCHITECTURE §7.9): подагрегат заявки (ADR-0020 §2).

Отклик живёт внутри заявки: лимит мест (`max_responses`, по умолчанию пять) — инвариант заявки,
поэтому отклик создаётся, правится и отзывается её методами под блокировкой строки заявки, а
каждое изменение отклика увеличивает версию заявки. Место занимают активные отклики —
отправленный, просмотренный и «в избранных клиента». Один исполнитель — один отклик на заявку:
отозванный не повторяется. Выбор клиента (6.1a): «в избранные», «отклонить» и «выбрать
исполнителем» — из отправленного отклик сначала становится просмотренным (§7.9).

Текст проверяет модерация (§14.1, адаптер цели `response`): клиент видит отклик, когда проверка
пройдена; с флагом — после решения модератора; нарушение скрывает отклик и освобождает место.
Место отклик занимает и на проверке — иначе счётчик «3 из 5» обгонял бы правду.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.jobs.errors import InvalidResponseError, ResponseNotActiveError
from app.platform.kernel.ids import UserId

ResponseId = NewType("ResponseId", UUID)

MAX_MESSAGE: Final = 1500
MAX_AVAILABILITY: Final = 200
MAX_PRICE: Final = 1_000_000_000 * 100
"""Миллиард динаров в пара: защита от опечатки в нулях (как у бюджета заявки)."""


class ResponseStatus(StrEnum):
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    SHORTLISTED = "shortlisted"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    NOT_SELECTED = "not_selected"


ACTIVE: Final = frozenset(
    {ResponseStatus.SUBMITTED, ResponseStatus.VIEWED, ResponseStatus.SHORTLISTED}
)
"""Ждут решения клиента и занимают место из `max_responses` (§7.9)."""

_ALLOWED: Final[dict[ResponseStatus, frozenset[ResponseStatus]]] = {
    ResponseStatus.SUBMITTED: frozenset(
        {ResponseStatus.VIEWED, ResponseStatus.WITHDRAWN, ResponseStatus.NOT_SELECTED}
    ),
    ResponseStatus.VIEWED: frozenset(
        {
            ResponseStatus.SHORTLISTED,
            ResponseStatus.DECLINED,
            ResponseStatus.ACCEPTED,
            ResponseStatus.WITHDRAWN,
            ResponseStatus.NOT_SELECTED,
        }
    ),
    ResponseStatus.SHORTLISTED: frozenset(
        {
            ResponseStatus.ACCEPTED,
            ResponseStatus.DECLINED,
            ResponseStatus.WITHDRAWN,
            ResponseStatus.NOT_SELECTED,
        }
    ),
    ResponseStatus.NOT_SELECTED: frozenset({ResponseStatus.VIEWED}),
    ResponseStatus.ACCEPTED: frozenset({ResponseStatus.DECLINED, ResponseStatus.WITHDRAWN}),
    ResponseStatus.DECLINED: frozenset(),
    ResponseStatus.WITHDRAWN: frozenset(),
}


class ResponseReview(StrEnum):
    """Проверка текста: клиент видит только `clear`."""

    PENDING = "pending"
    """Ждёт автопроверки или решения модератора."""
    CLEAR = "clear"
    BLOCKED = "blocked"
    """Скрыт модерацией: место освобождено."""


class ResponsePriceType(StrEnum):
    """Цена отклика S16: «Фикс», «От», «За час», «Договорная»."""

    FIXED = "fixed"
    FROM = "from"
    HOURLY = "hourly"
    NEGOTIABLE = "negotiable"


@dataclass(frozen=True, slots=True, kw_only=True)
class Offer:
    """Что исполнитель предлагает: сообщение клиенту, цена в пара и «когда смогу»."""

    message: str
    price_type: ResponsePriceType
    price_amount: int | None = None
    availability_note: str | None = None

    def __post_init__(self) -> None:
        message = self.message.strip()
        if not 1 <= len(message) <= MAX_MESSAGE:
            raise InvalidResponseError(field="message", reason="length")
        if self.price_type is ResponsePriceType.NEGOTIABLE:
            if self.price_amount is not None:
                raise InvalidResponseError(field="price_amount", reason="negotiable_has_amount")
        elif self.price_amount is None:
            raise InvalidResponseError(field="price_amount", reason="required")
        elif not 0 < self.price_amount <= MAX_PRICE:
            raise InvalidResponseError(field="price_amount", reason="out_of_range")
        note = (self.availability_note or "").strip() or None
        if note is not None and len(note) > MAX_AVAILABILITY:
            raise InvalidResponseError(field="availability_note", reason="too_long")
        if message != self.message:
            object.__setattr__(self, "message", message)
        if note != self.availability_note:
            object.__setattr__(self, "availability_note", note)


@dataclass(kw_only=True)
class Response:
    """Отклик исполнителя на заявку. Меняется только методами заявки (`Job.respond`, …).
    Сравнивается по значению: UoW сверяет снимок заявки вместе с откликами (забытый save)."""

    id: ResponseId
    performer_id: UserId
    status: ResponseStatus
    offer: Offer
    created_at: datetime
    updated_at: datetime
    profile_id: UUID | None = None
    """Профиль специалиста, от которого отклик; без профиля — подработка («Мастер на час»)."""
    template_id: UUID | None = None
    review: ResponseReview = ResponseReview.PENDING
    revision: int = 1
    """Растёт с каждой правкой: модерация публикует только ту редакцию, которую проверила."""
    viewed_at: datetime | None = None
    decided_at: datetime | None = None
    _changed: bool = field(default=False, repr=False, compare=False)
    """Новый или изменённый: репозиторий записывает только такие."""

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    @property
    def changed(self) -> bool:
        return self._changed

    def mark_saved(self) -> None:
        """Записан. Вызывает только репозиторий."""
        self._changed = False

    @property
    def visible_to_client(self) -> bool:
        return self.review is ResponseReview.CLEAR

    def revise(self, offer: Offer, *, now: datetime) -> None:
        """Исполнитель поправил отклик — пока клиент не решил: новая редакция снова на проверку
        и до неё скрыта от клиента."""
        if not self.is_active or self.review is ResponseReview.BLOCKED:
            raise ResponseNotActiveError(response_id=self.id, response_status=self.status.value)
        self.offer = offer
        self.review = ResponseReview.PENDING
        self.revision += 1
        self.updated_at = now
        self._changed = True

    def job_closed(self, *, now: datetime) -> None:
        """Заявку закрыли, сняли или удалили: активный отклик — «не выбран» (§7.9)."""
        if not self.is_active:
            return
        self._move(ResponseStatus.NOT_SELECTED, now=now)
        self.decided_at = now

    def clear(self, *, revision: int | None, now: datetime) -> bool:
        """Проверка пройдена: клиент видит отклик. Другая редакция (успели поправить), уже
        видимый или скрытый — ничего, False."""
        if self.review is not ResponseReview.PENDING:
            return False
        if revision is not None and revision != self.revision:
            return False
        self.review = ResponseReview.CLEAR
        self.updated_at = now
        self._changed = True
        return True

    def block(self, *, now: datetime) -> bool:
        """Нарушение: отклик скрыт; активный перестаёт занимать место (возвращает True)."""
        if self.review is ResponseReview.BLOCKED:
            return False
        freed = self.is_active
        self.review = ResponseReview.BLOCKED
        if freed:
            self._move(ResponseStatus.WITHDRAWN, now=now)
            self.decided_at = now
        self.updated_at = now
        self._changed = True
        return freed

    def accept(self, *, now: datetime) -> None:
        """Клиент выбрал отклик исполнителем: создана сделка (6.1a)."""
        self._see(now)
        self._move(ResponseStatus.ACCEPTED, now=now)
        self.decided_at = now

    def shortlist(self, *, now: datetime) -> bool:
        """Клиент добавил отклик в избранные; уже там — ничего, False."""
        if self.status is ResponseStatus.SHORTLISTED:
            return False
        self._see(now)
        self._move(ResponseStatus.SHORTLISTED, now=now)
        return True

    def decline(self, *, now: datetime) -> None:
        """Клиент отклонил отклик: место освобождается."""
        self._see(now)
        self._move(ResponseStatus.DECLINED, now=now)
        self.decided_at = now

    def deal_cancelled(self, *, by_performer: bool, now: datetime) -> None:
        """Сделку по выбранному отклику отменили (§7.9): исполнитель — «отозван», клиент или
        система — «отклонён»."""
        target = ResponseStatus.WITHDRAWN if by_performer else ResponseStatus.DECLINED
        self._move(target, now=now)
        self.decided_at = now

    def reconsider(self, *, now: datetime) -> None:
        """Сделку отменили — «не выбран» снова ждёт решения клиента как «просмотрен» (§7.9)."""
        self._move(ResponseStatus.VIEWED, now=now)
        self.decided_at = None

    def withdraw(self, *, now: datetime) -> None:
        """Исполнитель отозвал отклик, пока клиент не решил: место освобождается. Отказ от
        выбранного отклика — отмена сделки (6.1), не отзыв."""
        if not self.is_active:
            raise ResponseNotActiveError(response_id=self.id, response_status=self.status.value)
        self._move(ResponseStatus.WITHDRAWN, now=now)
        self.decided_at = now

    def _see(self, now: datetime) -> None:
        """Решение клиента начинается с просмотра: отправленный — «просмотрен»."""
        if self.status is ResponseStatus.SUBMITTED:
            self._move(ResponseStatus.VIEWED, now=now)
            self.viewed_at = now

    def _move(self, target: ResponseStatus, *, now: datetime) -> None:
        if target not in _ALLOWED[self.status]:
            raise ResponseNotActiveError(response_id=self.id, response_status=self.status.value)
        self.status = target
        self.updated_at = now
        self._changed = True
