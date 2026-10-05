"""Сделка (DEVELOPMENT_PLAN 6.1a; ARCHITECTURE §7.9, ADR-0016, ADR-0017): договорённость клиента
и исполнителя о работе. Деньги идут мимо платформы: цена — только запись договорённости в RSD.

- `agreed` — сразу, когда клиент выбрал отклик (`agree_from_response`): jobs создаёт сделку в
  своей транзакции через фасад;
- `proposed` → `agreed` — «Договорились» в чате одной стороной (`propose`, 6.4) и подтверждение
  второй (`confirm`);
- `agreed` → `completed` — обе стороны отметили «Работа выполнена» или одна, и 72 ч без возражений
  (`auto_complete`, задача `deals.auto_complete`, 6.1b);
- `proposed` или `agreed` → `cancelled` — сторона отменяет с причиной (пока никто не отметил
  «Работа выполнена»), система — предложение без ответа 72 ч (`expire_proposal`, 6.1b) и
  удалённый аккаунт;
- `agreed` → `disputed` → `completed` / `cancelled` — спор и решение модератора (6.1c,
  domain/dispute.py); `disputed` → `agreed` — открывший отозвал спор. Под спором сделку не
  завершить и не отменить, сроки 6.1b её не трогают.

Сроки (ARCHITECTURE §12.3, 6.1b): за 2 ч до времени сделки — напоминание сторонам (`remind`),
через 3 ч после него — «Работа выполнена?» (`prompt_completion`); у сделки без времени вопрос
приходит через сутки после договорённости. Каждое — один раз: отметка в сделке.

Переходы пишутся в `deals.status_history`: создание — без исходного статуса.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.deals.errors import (
    DealMarkedDoneError,
    DealNotActiveError,
    DealNotFoundError,
    InvalidDealError,
)
from app.platform.contracts.events.deals import (
    DealAgreed,
    DealCancelled,
    DealCompleted,
    DealCompletionDue,
    DealMarkedDone,
    DealProposed,
    DealReminderDue,
)
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.ids import CategoryId, DealId, UserId

MAX_TITLE: Final = 120
"""Как у заявки: название сделки — снимок названия заявки."""
MAX_PRICE: Final = 1_000_000_000 * 100
"""Миллиард динаров в пара: защита от опечатки в нулях (как у бюджета заявки и отклика)."""
REMINDER_LEAD: Final = timedelta(hours=2)
"""Напоминание сторонам — за 2 ч до времени сделки (§12.3)."""
PROMPT_DELAY: Final = timedelta(hours=3)
"""«Работа выполнена?» — через 3 ч после времени сделки (§12.3)."""
PROMPT_WITHOUT_TIME: Final = timedelta(hours=24)
"""Время не договорено (отклик без даты): вопрос — через сутки после договорённости."""
AUTO_COMPLETE_AFTER: Final = timedelta(hours=72)
"""Одна сторона отметила «выполнено», вторая молчит 72 ч — сделка завершена (§7.9)."""
PROPOSAL_TTL: Final = timedelta(hours=72)
"""«Договорились» без ответа второй стороны 72 ч — предложение истекло (§7.9)."""


class DealStatus(StrEnum):
    PROPOSED = "proposed"
    AGREED = "agreed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class DealOrigin(StrEnum):
    JOB_RESPONSE = "job_response"
    """Клиент выбрал отклик на заявку (в том числе на прямой запрос)."""
    DIRECT = "direct"
    """Договорились без заявки — из карточки специалиста (после MVP)."""
    CHAT = "chat"
    """«Договорились» в переписке (6.4)."""


class DealRole(StrEnum):
    CLIENT = "client"
    PERFORMER = "performer"


class DealPriceType(StrEnum):
    """Как понимать цену: значения — как у цены отклика S16."""

    FIXED = "fixed"
    FROM = "from"
    HOURLY = "hourly"
    NEGOTIABLE = "negotiable"


class DealCancelReason(StrEnum):
    PLANS_CHANGED = "plans_changed"
    """Планы изменились."""
    NO_AGREEMENT = "no_agreement"
    """Не договорились о цене или времени."""
    NO_CONTACT = "no_contact"
    """Вторая сторона не выходит на связь."""
    OTHER = "other"
    EXPIRED = "expired"
    """Предложение «Договорились» не подтвердили за 72 ч (6.1b)."""
    ACCOUNT_DELETED = "account_deleted"
    """Аккаунт одной из сторон удалён."""
    DISPUTE = "dispute"
    """Модератор отменил сделку по итогам спора (6.1c)."""


PARTY_CANCEL_REASONS: Final = frozenset(
    {
        DealCancelReason.PLANS_CHANGED,
        DealCancelReason.NO_AGREEMENT,
        DealCancelReason.NO_CONTACT,
        DealCancelReason.OTHER,
    }
)
"""Причины, которые выбирает сторона; остальные ставит система."""


class ActorKind(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    SYSTEM = "system"


SYSTEM: Final = "system"
"""Кто отменил, если не сторона: `cancelled_by` события DealCancelled."""
MODERATOR: Final = "moderator"
"""Отменил модератор решением по спору (6.1c)."""

ACTIVE: Final = frozenset({DealStatus.PROPOSED, DealStatus.AGREED, DealStatus.DISPUTED})
"""Сделка ещё идёт: в списках «активные», удаление аккаунта её отменяет."""
CANCELLABLE: Final = frozenset({DealStatus.PROPOSED, DealStatus.AGREED})

_ALLOWED: Final[dict[DealStatus, frozenset[DealStatus]]] = {
    DealStatus.PROPOSED: frozenset({DealStatus.AGREED, DealStatus.CANCELLED}),
    DealStatus.AGREED: frozenset({DealStatus.COMPLETED, DealStatus.CANCELLED, DealStatus.DISPUTED}),
    DealStatus.DISPUTED: frozenset({DealStatus.COMPLETED, DealStatus.CANCELLED, DealStatus.AGREED}),
    DealStatus.COMPLETED: frozenset(),
    DealStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class DealTransition:
    """Запись `deals.status_history`: кто, когда и почему. Создание — без `from_`."""

    from_: DealStatus | None
    to: DealStatus
    actor_id: UserId | None
    actor_kind: ActorKind
    reason: str | None
    at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DealTerms:
    """О чём договорились: название (снимок заявки), категория и цена в пара."""

    title: str
    category_id: CategoryId | None = None
    price_type: DealPriceType | None = None
    agreed_price: int | None = None
    scheduled_at: datetime | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not 1 <= len(title) <= MAX_TITLE:
            raise InvalidDealError(field="title", reason="length")
        if self.agreed_price is not None and not 0 < self.agreed_price <= MAX_PRICE:
            raise InvalidDealError(field="agreed_price", reason="out_of_range")
        if self.price_type is DealPriceType.NEGOTIABLE and self.agreed_price is not None:
            raise InvalidDealError(field="agreed_price", reason="negotiable_has_amount")
        if title != self.title:
            object.__setattr__(self, "title", title)


@dataclass(eq=False, kw_only=True)
class Deal(VersionedAggregate):
    id: DealId
    client_id: UserId
    performer_id: UserId
    origin: DealOrigin
    terms: DealTerms
    status: DealStatus
    created_at: datetime
    updated_at: datetime
    profile_id: UUID | None = None
    """Профиль специалиста исполнителя; без профиля — подработка («Мастер на час»)."""
    job_id: UUID | None = None
    """Ссылка вверх по DAG (jobs) — без FK."""
    response_id: UUID | None = None
    conversation_id: UUID | None = None
    proposed_by: UserId | None = None
    agreed_at: datetime | None = None
    client_confirmed_at: datetime | None = None
    performer_confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UserId | None = None
    cancel_reason: DealCancelReason | None = None
    reminded_at: datetime | None = None
    """Сторонам напомнили о времени сделки."""
    completion_prompted_at: datetime | None = None
    """Сторонам задали вопрос «Работа выполнена?»."""
    _history: list[DealTransition] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def agree_from_response(
        cls,
        *,
        deal_id: DealId,
        client_id: UserId,
        performer_id: UserId,
        profile_id: UUID | None,
        job_id: UUID,
        response_id: UUID,
        terms: DealTerms,
        now: datetime,
    ) -> Deal:
        """Клиент выбрал отклик: сделка сразу `agreed` (§7.9)."""
        deal = cls._new(
            deal_id=deal_id,
            client_id=client_id,
            performer_id=performer_id,
            origin=DealOrigin.JOB_RESPONSE,
            terms=terms,
            status=DealStatus.AGREED,
            now=now,
        )
        deal.profile_id, deal.job_id, deal.response_id = profile_id, job_id, response_id
        deal.agreed_at = now
        deal._history.append(
            DealTransition(
                from_=None,
                to=DealStatus.AGREED,
                actor_id=client_id,
                actor_kind=ActorKind.USER,
                reason="response_accepted",
                at=now,
            )
        )
        deal._record(deal._agreed_event(now))
        return deal

    @classmethod
    def propose(
        cls,
        *,
        deal_id: DealId,
        client_id: UserId,
        performer_id: UserId,
        proposed_by: UserId,
        profile_id: UUID | None,
        conversation_id: UUID | None,
        terms: DealTerms,
        now: datetime,
    ) -> Deal:
        """«Договорились» в чате одной стороной (6.3b): сделка ждёт подтверждения второй."""
        if proposed_by not in (client_id, performer_id):
            raise InvalidDealError(field="proposed_by", reason="not_a_party")
        deal = cls._new(
            deal_id=deal_id,
            client_id=client_id,
            performer_id=performer_id,
            origin=DealOrigin.CHAT,
            terms=terms,
            status=DealStatus.PROPOSED,
            now=now,
        )
        deal.profile_id, deal.conversation_id, deal.proposed_by = (
            profile_id,
            conversation_id,
            proposed_by,
        )
        deal._history.append(
            DealTransition(
                from_=None,
                to=DealStatus.PROPOSED,
                actor_id=proposed_by,
                actor_kind=ActorKind.USER,
                reason=None,
                at=now,
            )
        )
        deal._record(
            DealProposed(
                deal_id=deal_id,
                client_id=client_id,
                performer_id=performer_id,
                proposed_by=proposed_by,
                conversation_id=conversation_id,
                occurred_at=now,
            )
        )
        return deal

    def role_of(self, user_id: UserId | None) -> DealRole | None:
        if user_id == self.client_id:
            return DealRole.CLIENT
        if user_id == self.performer_id:
            return DealRole.PERFORMER
        return None

    def confirm(self, *, actor_id: UserId, now: datetime) -> None:
        """Вторая сторона подтвердила «Договорились»: `proposed` → `agreed`. Предложившая сторона
        подтвердить сама не может — ждёт вторую."""
        self._party(actor_id)
        if self.status is not DealStatus.PROPOSED or actor_id == self.proposed_by:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._move(DealStatus.AGREED, by=actor_id, kind=ActorKind.USER, now=now)
        self.agreed_at = now
        self._record(self._agreed_event(now))

    def complete(self, *, actor_id: UserId, now: datetime) -> bool:
        """Сторона отметила «Работа выполнена». Отметили обе — сделка `completed` (True);
        повторная отметка той же стороны ничего не меняет."""
        role = self._party(actor_id)
        if self.status is not DealStatus.AGREED:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        marked = False
        if role is DealRole.CLIENT and self.client_confirmed_at is None:
            self.client_confirmed_at = now
            self.updated_at, marked = now, True
        elif role is DealRole.PERFORMER and self.performer_confirmed_at is None:
            self.performer_confirmed_at = now
            self.updated_at, marked = now, True
        if self.client_confirmed_at is None or self.performer_confirmed_at is None:
            if marked:
                self._record(
                    DealMarkedDone(
                        deal_id=self.id,
                        client_id=self.client_id,
                        performer_id=self.performer_id,
                        marked_by=role.value,
                        occurred_at=now,
                    )
                )
            return False
        self._move(DealStatus.COMPLETED, by=actor_id, kind=ActorKind.USER, now=now)
        self.completed_at = now
        self._record(self._completed_event(now, auto=False))
        return True

    @property
    def completion_due_at(self) -> datetime | None:
        """Когда спросить «Работа выполнена?»; не договорились — None."""
        if self.terms.scheduled_at is not None:
            return self.terms.scheduled_at + PROMPT_DELAY
        if self.agreed_at is not None:
            return self.agreed_at + PROMPT_WITHOUT_TIME
        return None

    def remind(self, *, now: datetime) -> bool:
        """До времени сделки 2 ч или меньше: напомнить сторонам один раз (DealReminderDue).
        Время не договорено, уже прошло, напоминали или сделка не идёт — False."""
        when = self.terms.scheduled_at
        if self.status is not DealStatus.AGREED or when is None or self.reminded_at is not None:
            return False
        if not now < when <= now + REMINDER_LEAD:
            return False
        self.reminded_at = now
        self._record(
            DealReminderDue(
                deal_id=self.id,
                client_id=self.client_id,
                performer_id=self.performer_id,
                scheduled_at=when,
                occurred_at=now,
            )
        )
        return True

    def prompt_completion(self, *, now: datetime) -> bool:
        """Пора спросить «Работа выполнена?» (DealCompletionDue) — тех, кто ещё не отметил;
        один раз. Рано, уже спрашивали или сделка не идёт — False."""
        due = self.completion_due_at
        if self.status is not DealStatus.AGREED or self.completion_prompted_at is not None:
            return False
        if due is None or due > now:
            return False
        self.completion_prompted_at = now
        self._record(
            DealCompletionDue(
                deal_id=self.id,
                client_id=self.client_id,
                performer_id=self.performer_id,
                ask_client=self.client_confirmed_at is None,
                ask_performer=self.performer_confirmed_at is None,
                occurred_at=now,
            )
        )
        return True

    def auto_complete(self, *, now: datetime) -> bool:
        """Одна сторона отметила «выполнено», вторая не возразила 72 ч — сделка завершена
        системой (§7.9). Иначе — False."""
        if self.status is not DealStatus.AGREED:
            return False
        marks = [m for m in (self.client_confirmed_at, self.performer_confirmed_at) if m]
        if len(marks) != 1 or marks[0] + AUTO_COMPLETE_AFTER > now:
            return False
        self._move(DealStatus.COMPLETED, by=None, kind=ActorKind.SYSTEM, now=now, reason="auto")
        self.completed_at = now
        self._record(self._completed_event(now, auto=True))
        return True

    def expire_proposal(self, *, now: datetime) -> bool:
        """«Договорились» без ответа 72 ч — система отменяет предложение (`expired`)."""
        if self.status is not DealStatus.PROPOSED or self.created_at + PROPOSAL_TTL > now:
            return False
        return self.cancel_by_system(reason=DealCancelReason.EXPIRED, now=now)

    def cancel(self, *, actor_id: UserId, reason: DealCancelReason, now: datetime) -> None:
        """Сторона отменяет с причиной: идущую сделку или предложение «Договорились» (своё —
        отзывает, чужое — отклоняет). После отметки «Работа выполнена» любой из сторон — нельзя:
        иначе отмена стёрла бы отметку, а с ней отзыв и спор (MU-8). Вторая сторона
        подтверждает выполнение или открывает спор; молчит — через 72 ч сделка завершится."""
        role = self._party(actor_id)
        if reason not in PARTY_CANCEL_REASONS:
            raise InvalidDealError(field="reason", reason="not_allowed")
        if self.status not in CANCELLABLE:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        if self.client_confirmed_at is not None or self.performer_confirmed_at is not None:
            raise DealMarkedDoneError(deal_id=self.id)
        self._cancel(by=actor_id, by_role=role.value, kind=ActorKind.USER, reason=reason, now=now)

    def decline(self, *, actor_id: UserId, now: datetime) -> None:
        """«Отклонить» предложение «Договорились» (S53, кнопка в боте, 6.3b): только пока оно
        ждёт ответа — идущую сделку так не отменить (для неё `cancel` с причиной). Предложившая
        сторона так же отзывает своё."""
        role = self._party(actor_id)
        if self.status is not DealStatus.PROPOSED:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._cancel(
            by=actor_id,
            by_role=role.value,
            kind=ActorKind.USER,
            reason=DealCancelReason.NO_AGREEMENT,
            now=now,
        )

    def cancel_by_system(self, *, reason: DealCancelReason, now: datetime) -> bool:
        """Система отменяет: истекло предложение, удалён аккаунт. Уже завершена, отменена или
        под спором — ничего, False."""
        if self.status not in CANCELLABLE:
            return False
        self._cancel(by=None, by_role=SYSTEM, kind=ActorKind.SYSTEM, reason=reason, now=now)
        return True

    def open_dispute(self, *, actor_id: UserId, now: datetime) -> None:
        """Сторона открыла спор (Dispute.open): идущая сделка — `disputed`."""
        self._party(actor_id)
        if self.status is not DealStatus.AGREED:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._move(DealStatus.DISPUTED, by=actor_id, kind=ActorKind.USER, now=now, reason="dispute")

    def resume_after_dispute(self, *, actor_id: UserId, now: datetime) -> None:
        """Спор отозван: сделка снова идёт — отметки «Работа выполнена» и сроки прежние."""
        if self.status is not DealStatus.DISPUTED:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._move(
            DealStatus.AGREED,
            by=actor_id,
            kind=ActorKind.USER,
            now=now,
            reason="dispute_withdrawn",
        )

    def settle_dispute(
        self, *, target: DealStatus, moderator_id: UserId | None, now: datetime
    ) -> None:
        """Решение модератора по спору: `completed` (DealCompleted — заявка завершена, отзыв) или
        `cancelled` (DealCancelled от модератора — заявка снова открыта)."""
        if self.status is not DealStatus.DISPUTED:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        if target is DealStatus.COMPLETED:
            self._move(target, by=moderator_id, kind=ActorKind.MODERATOR, now=now, reason="dispute")
            self.completed_at = now
            self._record(self._completed_event(now, auto=False))
            return
        if target is not DealStatus.CANCELLED:
            raise InvalidDealError(field="outcome", reason="not_allowed")
        self._cancel(
            by=None,
            by_role=MODERATOR,
            kind=ActorKind.MODERATOR,
            reason=DealCancelReason.DISPUTE,
            now=now,
            actor_id=moderator_id,
        )

    def pull_history(self) -> list[DealTransition]:
        history, self._history = self._history, []
        return history

    @classmethod
    def _new(
        cls,
        *,
        deal_id: DealId,
        client_id: UserId,
        performer_id: UserId,
        origin: DealOrigin,
        terms: DealTerms,
        status: DealStatus,
        now: datetime,
    ) -> Deal:
        if client_id == performer_id:
            raise InvalidDealError(field="performer_id", reason="same_as_client")
        return cls(
            id=deal_id,
            client_id=client_id,
            performer_id=performer_id,
            origin=origin,
            terms=terms,
            status=status,
            created_at=now,
            updated_at=now,
            version=1,
        )

    def _party(self, actor_id: UserId) -> DealRole:
        """Роль участника; не участник — как несуществующая сделка (404)."""
        role = self.role_of(actor_id)
        if role is None:
            raise DealNotFoundError(deal_id=self.id)
        return role

    def _cancel(
        self,
        *,
        by: UserId | None,
        by_role: str,
        kind: ActorKind,
        reason: DealCancelReason,
        now: datetime,
        actor_id: UserId | None = None,
    ) -> None:
        """`by` — отменившая сторона (`cancelled_by`); модератор — только в истории
        (`actor_id`): стороне его отмена — не «отменил я» и не «вторая сторона»."""
        actor = by if actor_id is None else actor_id
        proposal = self.status is DealStatus.PROPOSED  # до подтверждения сделки ещё не было
        self._move(DealStatus.CANCELLED, by=actor, kind=kind, now=now, reason=reason.value)
        self.cancelled_at, self.cancelled_by, self.cancel_reason = now, by, reason
        self._record(
            DealCancelled(
                deal_id=self.id,
                client_id=self.client_id,
                performer_id=self.performer_id,
                origin=self.origin.value,
                job_id=self.job_id,
                response_id=self.response_id,
                category_id=self.terms.category_id,
                cancelled_by=by_role,
                reason=reason.value,
                proposal=proposal,
                conversation_id=self.conversation_id,
                occurred_at=now,
            )
        )

    def _completed_event(self, now: datetime, *, auto: bool) -> DealCompleted:
        return DealCompleted(
            deal_id=self.id,
            client_id=self.client_id,
            performer_id=self.performer_id,
            origin=self.origin.value,
            job_id=self.job_id,
            response_id=self.response_id,
            category_id=self.terms.category_id,
            auto=auto,
            occurred_at=now,
        )

    def _agreed_event(self, now: datetime) -> DealAgreed:
        return DealAgreed(
            deal_id=self.id,
            client_id=self.client_id,
            performer_id=self.performer_id,
            origin=self.origin.value,
            job_id=self.job_id,
            response_id=self.response_id,
            category_id=self.terms.category_id,
            occurred_at=now,
        )

    def _move(
        self,
        target: DealStatus,
        *,
        by: UserId | None,
        kind: ActorKind,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        if target not in _ALLOWED[self.status]:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._history.append(
            DealTransition(
                from_=self.status, to=target, actor_id=by, actor_kind=kind, reason=reason, at=now
            )
        )
        self.status = target
        self.updated_at = now
