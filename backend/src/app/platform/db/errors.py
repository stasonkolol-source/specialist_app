"""Ошибки программиста вокруг Unit of Work (ADR-0020 §4, §9): 500, Sentry, алерт."""

from app.platform.kernel.errors import ProgrammingError


class NestedTransactionError(ProgrammingError):
    """Второй `async with uow` при активном блоке. Savepoint'ы в модулях не используем."""


class WriteOutsideUnitOfWorkError(ProgrammingError):
    """В сессии есть изменения вне `async with uow`, или запись вызвана без активного UoW."""


class UnsavedAggregateError(ProgrammingError):
    """Агрегат изменили, но не передали в `repository.save()` до конца блока."""


class FailedTransactionError(ProgrammingError):
    """Транзакция в состоянии ошибки: PostgreSQL превратил бы COMMIT в тихий ROLLBACK
    (docs/spikes/0.8). Где-то ошибку SQL проглотили без отката к savepoint."""
