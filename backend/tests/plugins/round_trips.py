"""Счётчик обменов с PostgreSQL в тесте: регрессии «сколько запросов у экрана» (перф-аудит).

Экран медленный не от тяжёлых запросов, а от их числа: каждый — обмен с базой. Считаются
запросы SQLAlchemy, BEGIN и COMMIT/ROLLBACK, которые psycopg действительно шлёт на сервер (в
AUTOCOMMIT их нет), и выдачи соединения пулом — с `pool_pre_ping` каждая стоит проверки
соединения. Задачи Procrastinate UoW ставит мимо SQLAlchemy (драйвером): их тут нет.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from psycopg.pq import TransactionStatus
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class RoundTrips:
    statements: list[str] = field(default_factory=list)
    begins: int = 0
    ends: int = 0
    """COMMIT и ROLLBACK, дошедшие до сервера."""
    checkouts: int = 0
    pre_ping: bool = False

    @property
    def queries(self) -> int:
        """Запросы приложения, без управления транзакцией."""
        return len(self.statements)

    @property
    def total(self) -> int:
        """Все обмены: проверки соединения, BEGIN, запросы, COMMIT/ROLLBACK."""
        pings = self.checkouts if self.pre_ping else 0
        return pings + self.begins + self.queries + self.ends

    def reset(self) -> None:
        self.statements.clear()
        self.begins = self.ends = self.checkouts = 0


def _driver(conn: Connection) -> Any:
    return conn.connection.driver_connection


@contextmanager
def round_trips(engine: AsyncEngine) -> Iterator[RoundTrips]:
    """Считать обмены движка внутри блока (все сессии и соединения этого движка)."""
    sync = engine.sync_engine
    counter = RoundTrips(pre_ping=bool(getattr(sync.pool, "_pre_ping", False)))

    def before_execute(conn: Connection, cursor: object, statement: str, *_: object) -> None:
        driver = _driver(conn)
        if not driver.autocommit and driver.info.transaction_status == TransactionStatus.IDLE:
            counter.begins += 1  # psycopg начнёт транзакцию перед этим запросом
        counter.statements.append(statement)

    def finish(conn: Connection) -> None:
        if _driver(conn).info.transaction_status != TransactionStatus.IDLE:
            counter.ends += 1

    def checkout(*_: object) -> None:
        counter.checkouts += 1

    listeners: list[tuple[Any, str, Any]] = [
        (sync, "before_cursor_execute", before_execute),
        (sync, "commit", finish),
        (sync, "rollback", finish),
        (sync.pool, "checkout", checkout),
    ]
    for target, name, fn in listeners:
        event.listen(target, name, fn)
    try:
        yield counter
    finally:
        for target, name, fn in listeners:
            event.remove(target, name, fn)


__all__ = ["RoundTrips", "round_trips"]
