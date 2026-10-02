"""Порты deals (ADR-0020 §1): репозиторий сделки и чтение для экранов S25, S26 и списков."""

from collections.abc import Sequence
from typing import Protocol

from app.modules.deals.application.dto import DealView
from app.modules.deals.domain.deal import Deal, DealRole, DealStatus
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest


class DealRepository(Protocol):
    async def add(self, deal: Deal) -> None: ...

    async def get_for_update(self, deal_id: DealId) -> Deal:
        """Сделка под блокировкой строки; нет — DealNotFoundError."""
        ...

    async def save(self, deal: Deal) -> None: ...


class DealQueries(Protocol):
    """Чтение сделок для экранов: без блокировок и UoW."""

    async def view(self, deal_id: DealId) -> DealView | None: ...

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
