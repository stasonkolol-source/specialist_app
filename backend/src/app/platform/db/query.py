"""База query-сервисов (CQRS-lite, ADR-0020 §4–5): Core select() → frozen dataclass, keyset.

Вне активного Unit of Work транзакция чтения завершается сразу после запроса, и
соединение возвращается в пул: хендлер, который ждёт Telegram, не держит «idle in
transaction». Флаг активного UoW ставит SqlAlchemyUnitOfWork (шаг 0.10).
"""

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable

from app.platform.kernel.pagination import InvalidCursorError

UOW_ACTIVE = "uow_active"
"""Ключ в session.info: UoW открыт — чтения идут в его транзакции."""


class SqlQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch(self, stmt: Executable) -> Sequence[RowMapping]:
        rows = (await self._session.execute(stmt)).mappings().all()
        await self._release()
        return rows

    async def _fetch_one(self, stmt: Executable) -> RowMapping | None:
        row = (await self._session.execute(stmt)).mappings().one_or_none()
        await self._release()
        return row

    async def _release(self) -> None:
        if not self._session.info.get(UOW_ACTIVE):
            await self._session.rollback()


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
