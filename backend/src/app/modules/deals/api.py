"""Контракт модуля deals для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из deals только этот файл.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.deals.errors import DealNotFoundError as DealNotFoundError
from app.modules.deals.errors import DisputeNotFoundError as DisputeNotFoundError
from app.modules.deals.errors import DisputeStateError as DisputeStateError
from app.modules.deals.errors import InvalidDealError as InvalidDealError
from app.modules.deals.errors import InvalidDisputeError as InvalidDisputeError
from app.platform.kernel.ids import CategoryId, DealId, MediaId, UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class AgreedDealIn:
    """Клиент выбрал отклик (jobs, 6.1a): условия — из отклика, название — снимок заявки."""

    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    job_id: UUID
    response_id: UUID
    title: str
    category_id: CategoryId
    price_type: str
    """Цена отклика: `fixed`, `from`, `hourly`, `negotiable`."""
    agreed_price: int | None
    """Пара; у договорной — None."""
    scheduled_at: datetime | None = None
    """Время работы, если заявка его называет (окно «Сегодня 18–21», дата и время): по нему —
    напоминание и «Работа выполнена?» (6.1b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposedDealIn:
    """«Договорились» в чате (переписка, 6.3b): условия задаёт нажавшая сторона, вторая
    подтверждает или отклоняет за 72 ч."""

    client_id: UserId
    performer_id: UserId
    proposed_by: UserId
    profile_id: UUID | None
    conversation_id: UUID
    title: str
    category_id: CategoryId | None = None
    price_type: str | None = None
    """Как у цены отклика: `fixed`, `from`, `hourly`, `negotiable`; None — цену не назвали."""
    agreed_price: int | None = None
    scheduled_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealBrief:
    """Сделка для уведомлений сторонам (6.1b) и переписки (6.3b): название, статус, стороны и
    время."""

    id: DealId
    client_id: UserId
    performer_id: UserId
    title: str
    status: str
    """DealStatus: уведомление нужно, пока сделка в ожидаемом статусе."""
    origin: str
    scheduled_at: datetime | None
    price_type: str | None = None
    """Как у цены отклика: `fixed`, `from`, `hourly`, `negotiable`; None — цену не называли."""
    agreed_price: int | None = None
    """Пара."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DisputeSummary:
    """Спор по сделке (6.1c): сторонам — экран S52, модератору — `cli dispute-show`. Значения
    перечислений — строками: `status` (`open`, `answered`, `no_response`, `resolved`,
    `withdrawn`), `kind`, `outcome` (`completed` | `cancelled`)."""

    id: UUID
    deal_id: DealId
    status: str
    kind: str
    opened_by: UserId
    respondent_id: UserId
    description: str
    media_ids: tuple[MediaId, ...]
    """Фото открывшего: приватный бакет, адреса — сторонам и модератору."""
    respond_by: datetime
    response: str | None
    response_media_ids: tuple[MediaId, ...]
    responded_at: datetime | None
    unanswered_at: datetime | None
    withdrawn_at: datetime | None
    outcome: str | None
    reason_code: str | None
    resolved_by: UserId | None
    resolved_at: datetime | None
    created_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status in {"open", "answered", "no_response"}


@dataclass(frozen=True, slots=True, kw_only=True)
class DealSummary:
    """Сделка стороне — экран сделки S26 (6.2): условия, стороны и вехи. Значения перечислений —
    строками: `status` (DealStatus), `origin`, `my_role` (`client` | `performer`), цена — пара."""

    id: DealId
    status: str
    origin: str
    my_role: str
    title: str
    price_type: str | None
    agreed_price: int | None
    scheduled_at: datetime | None
    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None
    proposed_by: UserId | None
    agreed_at: datetime | None
    client_confirmed_at: datetime | None
    performer_confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: UserId | None
    cancel_reason: str | None
    created_at: datetime
    version: int
    proposal_expires_at: datetime | None = None
    """Предложение «Договорились» истечёт тогда (S53); у других статусов — None."""
    completion_due_at: datetime | None = None
    """Идущей сделке — когда бот спросит «Работа выполнена?» (через 3 ч после времени работы, без
    времени — через сутки после договорённости); у других статусов — None."""
    category_id: CategoryId | None = None
    """Категория заявки сделки: отзыв по ней считается в среднем категории (7.2)."""
    dispute: DisputeSummary | None = None
    """Последний спор (6.1c) — только у `deal_card`; другие методы его не читают."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SettleDisputeIn:
    """Решение модератора по спору (moderation ResolveDispute)."""

    dispute_id: UUID
    outcome: str
    """`completed` — работа выполнена, `cancelled` — сделка отменена."""
    reason_code: str
    moderator_id: UserId | None


class DealsApi(Protocol):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        """Сделка `agreed` в транзакции вызывающего: нужен активный UoW (ADR-0020 §4)."""
        ...

    async def propose(self, data: ProposedDealIn) -> DealId:
        """Сделка `proposed` в транзакции вызывающего: нужен активный UoW. InvalidDealError —
        условия не проходят (пустое название, цена вне диапазона)."""
        ...

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        """Название, статус и стороны сделки; None — нет такой."""
        ...

    async def deal_briefs(self, deal_ids: Collection[DealId]) -> dict[DealId, DealBrief]:
        """Сделки пачкой (статус в списке диалогов S29); каких нет — нет и в ответе."""
        ...

    async def deal_for_response(self, response_id: UUID) -> DealBrief | None:
        """Сделка по отклику (одна на отклик); нет — None. Переписка открывает контакты после
        `agreed` (6.3a)."""
        ...

    async def completed_deals(self, user_id: UserId) -> int:
        """Сколько сделок человека в любой роли завершено — контекст карточки кейса в чате
        модераторов (2.5b)."""
        ...

    async def ever_agreed_pair(self, client_id: UserId, performer_id: UserId) -> bool:
        """Договаривались ли эти двое хоть раз (ADR-0010, решение владельца 2026-10-04): любая
        их сделка — в любом диалоге, по отклику или из чата, в любой роли — дошла до `agreed` и
        потом могла завершиться, отмениться или уйти в спор. Предложение, которое отклонили или
        которое истекло, не в счёт. Переписка так держит контакты пары открытыми."""
        ...

    async def agreed_pairs(
        self, pairs: Collection[tuple[UserId, UserId]]
    ) -> frozenset[tuple[UserId, UserId]]:
        """`ever_agreed_pair` пачкой (список диалогов S29): пары (клиент, исполнитель); в ответе —
        те из них, что договаривались. Один запрос по индексу на страницу."""
        ...

    async def deal_for(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        """Сделка стороне; не участник или нет такой — DealNotFoundError (404)."""
        ...

    async def my_deals(self, viewer_id: UserId, page: PageRequest) -> Page[DealSummary]:
        """Свои сделки в обеих ролях, новые первыми (S28 «Сделки и отзывы», 7.3)."""
        ...

    async def deal_card(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        """Сделка стороне с последним спором (`dispute`: идущий, решённый или отозванный; S26,
        S52) — одним запросом. Не участник или нет сделки — DealNotFoundError (404)."""
        ...

    async def dispute(self, dispute_id: UUID) -> DisputeSummary | None:
        """Спор по id — модерации (кейс `dispute`) и уведомлениям; нет такого — None."""
        ...

    async def settle_dispute(self, data: SettleDisputeIn) -> DisputeSummary:
        """Решение модератора в транзакции вызывающего (нужен активный UoW): сделка завершена
        или отменена, спор решён. DisputeNotFoundError — нет спора; DisputeStateError — уже
        решён или отозван; InvalidDisputeError — неизвестный исход или код причины."""
        ...

    async def disputing(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        """Кто из пользователей — сторона идущего спора: удаление аккаунта ждёт решения (legal
        hold, §7.10). Читает в транзакции вызывающего."""
        ...

    async def dispute_evidence_held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        """Какие файлы — доказательства идущего спора: `media.purge_deleted` их не стирает.
        Читает в транзакции вызывающего."""
        ...

    async def disputed_deals(self, deal_ids: Collection[DealId]) -> frozenset[DealId]:
        """У каких сделок идёт спор: переписку по ним срок хранения не удаляет (legal hold,
        §7.10). Читает в транзакции вызывающего."""
        ...
