"""Unit of Work на AsyncSession (ADR-0020 §4, ADR-0008; уточнён спайками 0.8 и шагом 0.7b).

- Один экземпляр на REQUEST scope (HTTP-запрос, Telegram-update, задача). Последовательные
  блоки разрешены, вложенные — нет.
- `session.begin()` не вызывается: UoW ведёт свой флаг, а транзакцию, открытую чтением
  (autobegin), откатывает — если в ней нет изменений.
- Выход без исключения: забытый save → UnsavedAggregateError; flush; события агрегатов и
  add_event → задачи подписчикам на том же соединении; проверка INERROR; COMMIT.
- Исключение в блоке или при commit: ROLLBACK, сессия снова пригодна.
- StaleDataError (строку изменили параллельно) → ConcurrentModificationError (409).
"""

from types import TracebackType
from typing import Self

import psycopg
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.platform.db.errors import (
    FailedTransactionError,
    NestedTransactionError,
    UnsavedAggregateError,
    WriteOutsideUnitOfWorkError,
)
from app.platform.db.query import UOW_ACTIVE
from app.platform.kernel.aggregate import AggregateRoot, aggregate_state
from app.platform.kernel.errors import ConcurrentModificationError
from app.platform.kernel.events import DomainEvent
from app.platform.queue.dispatcher import EventDispatcher
from app.platform.queue.procrastinate_queue import session_driver_connection


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession, dispatcher: EventDispatcher) -> None:
        self._session = session
        self._dispatcher = dispatcher
        self._active = False
        self._tracked: dict[int, tuple[AggregateRoot, dict[str, object]]] = {}
        self._events: list[DomainEvent] = []

    async def __aenter__(self) -> Self:
        if self._active:
            raise NestedTransactionError("nested `async with uow` is not allowed")
        if self._session.in_transaction():
            if self._session.new or self._session.dirty or self._session.deleted:
                raise WriteOutsideUnitOfWorkError("session has changes made outside UnitOfWork")
            await self._session.rollback()  # были только чтения — терять нечего
        self._active = True
        self._session.info[UOW_ACTIVE] = True
        return self

    def track(self, aggregate: AggregateRoot) -> None:
        self.require_active()
        self._tracked[id(aggregate)] = (aggregate, aggregate_state(aggregate))

    def add_event(self, event: DomainEvent) -> None:
        self.require_active()
        self._events.append(event)

    def require_active(self) -> None:
        if not self._active:
            raise WriteOutsideUnitOfWorkError(
                "no active UnitOfWork: wrap the command in `async with uow`"
            )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc is not None:
                await self._session.rollback()
                if isinstance(exc, StaleDataError):
                    raise ConcurrentModificationError() from exc
                return  # исходное исключение летит дальше
            try:
                self._ensure_saved()
                await self._session.flush()
                events = self._pull_events()
                if events:
                    await self._dispatcher.enqueue(events)
                await self._ensure_not_failed()
                await self._session.commit()
            except BaseException as err:
                await self._session.rollback()
                if isinstance(err, StaleDataError):
                    raise ConcurrentModificationError() from err
                raise
        finally:
            self._reset()

    def _ensure_saved(self) -> None:
        for aggregate, snapshot in self._tracked.values():
            if aggregate_state(aggregate) != snapshot:
                raise UnsavedAggregateError(
                    f"{type(aggregate).__name__} changed but repository.save() was not called"
                )

    def _pull_events(self) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for aggregate, _ in self._tracked.values():
            events.extend(aggregate.pull_events())
        events.extend(self._events)
        self._events = []
        return events

    async def _ensure_not_failed(self) -> None:
        """COMMIT транзакции в состоянии ошибки PostgreSQL молча превращает в ROLLBACK."""
        if not self._session.in_transaction():
            return
        driver = await session_driver_connection(self._session)
        if driver.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
            raise FailedTransactionError("transaction is in failed state; refusing silent rollback")

    def _reset(self) -> None:
        self._active = False
        self._tracked.clear()
        self._events.clear()
        self._session.info.pop(UOW_ACTIVE, None)
