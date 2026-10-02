"""Сделка (DEVELOPMENT_PLAN 6.1a; ARCHITECTURE §7.9, ADR-0016, ADR-0017): договорённость клиента
и исполнителя о работе. Деньги идут мимо платформы: цена — только запись договорённости в RSD.

- `agreed` — сразу, когда клиент выбрал отклик (`agree_from_response`): jobs создаёт сделку в
  своей транзакции через фасад;
- `proposed` → `agreed` — «Договорились» в чате одной стороной (`propose`, 6.4) и подтверждение
  второй (`confirm`);
- `agreed` → `completed` — обе стороны отметили «Работа выполнена» (одна и 72 ч без возражений —
  задача `deals.auto_complete`, 6.1b);
- `proposed` или `agreed` → `cancelled` — сторона отменяет с причиной, система — истёкшее
  предложение (6.1b) и удалённый аккаунт;
- `agreed` → `disputed` → `completed` / `cancelled` — спор и решение модератора (6.1c).

Переходы пишутся в `deals.status_history`: создание — без исходного статуса.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.deals.errors import DealNotActiveError, DealNotFoundError, InvalidDealError
from app.platform.contracts.events.deals import DealAgreed, DealCancelled, DealCompleted
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.ids import CategoryId, DealId, UserId

MAX_TITLE: Final = 120
"""Как у заявки: название сделки — снимок названия заявки."""
MAX_PRICE: Final = 1_000_000_000 * 100
"""Миллиард динаров в пара: защита от опечатки в нулях (как у бюджета заявки и отклика)."""


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

ACTIVE: Final = frozenset({DealStatus.PROPOSED, DealStatus.AGREED, DealStatus.DISPUTED})
"""Сделка ещё идёт: в списках «активные», удаление аккаунта её отменяет."""
CANCELLABLE: Final = frozenset({DealStatus.PROPOSED, DealStatus.AGREED})

_ALLOWED: Final[dict[DealStatus, frozenset[DealStatus]]] = {
    DealStatus.PROPOSED: frozenset({DealStatus.AGREED, DealStatus.CANCELLED}),
    DealStatus.AGREED: frozenset({DealStatus.COMPLETED, DealStatus.CANCELLED, DealStatus.DISPUTED}),
    DealStatus.DISPUTED: frozenset({DealStatus.COMPLETED, DealStatus.CANCELLED}),
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
        """«Договорились» в чате одной стороной (6.4): сделка ждёт подтверждения второй."""
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
        if role is DealRole.CLIENT and self.client_confirmed_at is None:
            self.client_confirmed_at = now
            self.updated_at = now
        elif role is DealRole.PERFORMER and self.performer_confirmed_at is None:
            self.performer_confirmed_at = now
            self.updated_at = now
        if self.client_confirmed_at is None or self.performer_confirmed_at is None:
            return False
        self._move(DealStatus.COMPLETED, by=actor_id, kind=ActorKind.USER, now=now)
        self.completed_at = now
        self._record(
            DealCompleted(
                deal_id=self.id,
                client_id=self.client_id,
                performer_id=self.performer_id,
                origin=self.origin.value,
                job_id=self.job_id,
                response_id=self.response_id,
                category_id=self.terms.category_id,
                occurred_at=now,
            )
        )
        return True

    def cancel(self, *, actor_id: UserId, reason: DealCancelReason, now: datetime) -> None:
        """Сторона отменяет с причиной: идущую сделку или предложение «Договорились» (своё —
        отзывает, чужое — отклоняет)."""
        role = self._party(actor_id)
        if reason not in PARTY_CANCEL_REASONS:
            raise InvalidDealError(field="reason", reason="not_allowed")
        if self.status not in CANCELLABLE:
            raise DealNotActiveError(deal_id=self.id, deal_status=self.status.value)
        self._cancel(by=actor_id, by_role=role.value, kind=ActorKind.USER, reason=reason, now=now)

    def cancel_by_system(self, *, reason: DealCancelReason, now: datetime) -> bool:
        """Система отменяет: истекло предложение, удалён аккаунт. Уже завершена, отменена или
        под спором — ничего, False."""
        if self.status not in CANCELLABLE:
            return False
        self._cancel(by=None, by_role=SYSTEM, kind=ActorKind.SYSTEM, reason=reason, now=now)
        return True

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
    ) -> None:
        self._move(DealStatus.CANCELLED, by=by, kind=kind, now=now, reason=reason.value)
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
                occurred_at=now,
            )
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
