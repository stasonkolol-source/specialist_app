"""Порты deals (ADR-0020 §1): репозитории сделки и спора, чтение для экранов S25, S26, S52 и
списков, задачи."""

from collections.abc import Collection, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from app.modules.deals.application.dto import DealView, DisputeView
from app.modules.deals.domain.deal import Deal, DealRole, DealStatus
from app.modules.deals.domain.dispute import Dispute, DisputeId
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import DealId, MediaId, UserId
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef


class DealSweep(StrEnum):
    """Проход периодической задачи по срокам сделок (6.1b, ARCHITECTURE §12.3)."""

    REMIND = "remind"
    """`deals.reminders`: за 2 ч до времени сделки — напоминание сторонам."""
    PROMPT = "prompt"
    """`deals.completion_prompts`: время прошло — «Работа выполнена?»."""
    AUTO_COMPLETE = "auto_complete"
    """`deals.auto_complete`: одна сторона отметила «выполнено», 72 ч без возражений."""
    EXPIRE_PROPOSALS = "expire_proposals"
    """`deals.expire_proposed`: «Договорились» без ответа 72 ч."""


class DealRepository(Protocol):
    async def add(self, deal: Deal) -> None: ...

    async def get_for_update(self, deal_id: DealId) -> Deal:
        """Сделка под блокировкой строки; нет — DealNotFoundError."""
        ...

    async def save(self, deal: Deal) -> None: ...

    async def cancellable_of(self, user_id: UserId) -> list[DealId]:
        """Сделки пользователя-стороны, которые ещё можно отменить (`proposed`, `agreed`)."""
        ...


class DealQueries(Protocol):
    """Чтение сделок для экранов: без блокировок и UoW."""

    async def view(self, deal_id: DealId) -> DealView | None: ...

    async def view_with_dispute(
        self, deal_id: DealId
    ) -> tuple[DealView, DisputeView | None] | None:
        """Сделка и её последний спор одним запросом (карточка S26, экран S52)."""
        ...

    async def views(self, deal_ids: Collection[DealId]) -> list[DealView]:
        """Сделки пачкой (статус в списке диалогов S29); каких нет — нет и в ответе."""
        ...

    async def mine(
        self,
        user_id: UserId,
        *,
        role: DealRole | None,
        statuses: Sequence[DealStatus],
        page: PageRequest,
    ) -> Page[DealView]:
        """Сделки, где человек — сторона (`role` — какая; None — любая), новые первыми; пустые
        `statuses` — все."""
        ...

    async def of_response(self, response_id: UUID) -> DealId | None:
        """Сделка по отклику (одна на отклик)."""
        ...

    async def due(self, sweep: DealSweep, now: datetime, *, limit: int) -> list[DealId]:
        """Сделки, которым пора в этот проход, — давние первыми."""
        ...


class DisputeRepository(Protocol):
    async def add(self, dispute: Dispute) -> None: ...

    async def active_for_update(self, deal_id: DealId) -> Dispute:
        """Идущий спор сделки под блокировкой строки; нет — DisputeNotFoundError."""
        ...

    async def get_for_update(self, dispute_id: DisputeId) -> Dispute:
        """Спор под блокировкой строки; нет — DisputeNotFoundError."""
        ...

    async def save(self, dispute: Dispute) -> None: ...


class DisputeQueries(Protocol):
    """Чтение споров: экран S52, модерация, legal hold. Без блокировок; внутри UoW — в его
    транзакции (legal hold читает в транзакции очистки media и удаления аккаунта)."""

    async def view(self, dispute_id: DisputeId) -> DisputeView | None: ...

    async def unanswered_due(self, now: datetime, *, limit: int) -> list[DisputeId]:
        """Споры, у которых срок ответа вышел, а ответа нет, — давние первыми."""
        ...

    async def disputing(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        """Кто из пользователей — сторона идущего спора."""
        ...

    async def evidence_held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        """Какие файлы — доказательства идущего спора."""
        ...


CANCEL_USER_DEALS: Final = TaskRef("deals.cancel_user_deals", UserDeleted)
"""Аккаунт удалён — его идущие сделки и предложения отменяются; сделка под спором ждёт решения
модератора (6.1c)."""
