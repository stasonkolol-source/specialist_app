"""Порт Unit of Work (ADR-0020 §4). Его видит application; адаптер — platform/db/uow.py."""

from types import TracebackType
from typing import Protocol, Self

from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.events import DomainEvent


class UnitOfWork(Protocol):
    """Одна команда — одна транзакция — один `async with uow`."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def track(self, aggregate: AggregateRoot) -> None:
        """Репозиторий в get, add, save: снимок для проверки забытого save и сбора событий."""
        ...

    def add_event(self, event: DomainEvent) -> None:
        """Событие без агрегата — только внутри блока."""
        ...

    def require_active(self) -> None:
        """Командный метод фасада, простая запись, платформенные порты: только внутри блока."""
        ...
