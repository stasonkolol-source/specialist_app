"""База query-сервисов (CQRS-lite, ADR-0020 §4–5): Core select() → frozen dataclass, keyset.

Вне активного Unit of Work транзакция чтения завершается сразу после запроса, и
соединение возвращается в пул: хендлер, который ждёт Telegram, не держит «idle in
transaction». Флаг активного UoW ставит SqlAlchemyUnitOfWork (шаг 0.10).

Одиночное чтение вне UoW идёт на соединении в AUTOCOMMIT: psycopg не шлёт BEGIN перед
запросом, а откат после него — пустая операция (транзакции на сервере нет). Вместо четырёх
обменов с базой (проверка соединения, BEGIN, SELECT, ROLLBACK) — два. Каждый такой запрос и
раньше шёл в своей транзакции, так что снимок данных между запросами не общий ни там, ни тут;
блокировки и `SET LOCAL` живут только в транзакциях UoW. Уровень изоляции соединения пул
возвращает к обычному при возврате (SQLAlchemy), и UoW получает транзакцию как прежде.
Сессия, привязанная к внешнему соединению (тест в откатываемой транзакции), читает в нём.
"""

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, TypeVarTuple, overload
from uuid import UUID

from sqlalchemy import Result, RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.sql import Executable
from sqlalchemy.sql.selectable import TypedReturnsRows

from app.platform.kernel.pagination import InvalidCursorError

UOW_ACTIVE = "uow_active"
"""Ключ в session.info: UoW открыт — чтения идут в его транзакции."""
_AUTOCOMMIT: Final = {"isolation_level": "AUTOCOMMIT"}
_Ts = TypeVarTuple("_Ts")


class SqlQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch(self, stmt: Executable) -> Sequence[RowMapping]:
        try:
            return (await self._execute(stmt)).mappings().all()
        finally:
            await self._release()

    async def _fetch_one(self, stmt: Executable) -> RowMapping | None:
        try:
            return (await self._execute(stmt)).mappings().one_or_none()
        finally:
            await self._release()

    @overload
    async def _execute(self, stmt: TypedReturnsRows[*_Ts]) -> Result[*_Ts]: ...

    @overload
    async def _execute(self, stmt: Executable) -> Result[*tuple[Any, ...]]: ...

    async def _execute(self, stmt: Executable) -> Result[*tuple[Any, ...]]:
        """Запрос query-сервиса; результат разбирается до `_release` (строки ORM после него
        истекают). Вне UoW — на соединении в AUTOCOMMIT (см. docstring модуля)."""
        if self._standalone():
            await self._session.connection(execution_options=_AUTOCOMMIT)
        return await self._session.execute(stmt)

    async def _release(self) -> None:
        if not self._session.info.get(UOW_ACTIVE):
            await self._session.rollback()

    def _standalone(self) -> bool:
        """Чтение само по себе: не в UoW, соединения у сессии ещё нет, и она берёт его из
        пула движка, а не работает во внешнем соединении."""
        return (
            not self._session.info.get(UOW_ACTIVE)
            and not self._session.in_transaction()
            and isinstance(self._session.bind, AsyncEngine)
        )


def encode_cursor(*values: Any) -> str:
    """Непрозрачный курсор keyset-пагинации из значений ключа сортировки."""
    payload = [_to_json(v) for v in values]
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, types: Sequence[type]) -> tuple[Any, ...]:
    """Разобрать курсор; типы значений — как в encode_cursor. Мусор → InvalidCursorError."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(values, list) or len(values) != len(types):
            raise InvalidCursorError
        return tuple(_from_json(v, t) for v, t in zip(values, types, strict=True))
    except (ValueError, binascii.Error, TypeError, AttributeError, json.JSONDecodeError) as exc:
        # AttributeError — UUID(123): курсор подделан, а не битый
        raise InvalidCursorError from exc


def _to_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _from_json(value: Any, target: type) -> Any:
    if target is datetime:
        return datetime.fromisoformat(value)
    if target is UUID:
        return UUID(value)
    return target(value)
