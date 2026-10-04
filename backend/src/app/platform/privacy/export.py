"""Выгрузка данных пользователя по запросу (ZZPL ст. 21, 26; DEVELOPMENT_PLAN 2.12b).

`cli export-user-data <user_id>`: разделы всех модулей из реестра — их строки в таблицах и
дополнения (ссылки на файлы) — в один JSON. Выгрузка — просмотр ПД персоналом: запись
`privacy.user_data.exported` в audit_log (§7.10) идёт своей транзакцией после сборки.
"""

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.privacy.registry import PRIVACY, ExportSection, PrivacyRegistry, table_of

EXPORT_FORMAT = 1
"""Версия формата файла: поддержка отвечает пользователю, что в каком разделе."""
EXPORTED = "privacy.user_data.exported"


def jsonable(value: Any) -> Any:
    """Значение колонки — в JSON: UUID и время строкой, перечисления значением."""
    match value:
        case None | bool() | int() | float() | str():
            return value
        case UUID() | Decimal():
            return str(value)
        case datetime() | date() | time():
            return value.isoformat()
        case Enum():
            return jsonable(value.value)
        case bytes():
            return None  # двоичное (хэши) в выгрузку не идёт
        case Mapping():
            return {str(key): jsonable(item) for key, item in value.items()}
        case list() | tuple() | set() | frozenset():
            return [jsonable(item) for item in value]
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
        case _:
            return str(value)


async def _section(
    container: AsyncContainer, section: ExportSection, user_id: UUID
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    async with container() as request:
        session = await request.get(AsyncSession)
        for spec in section.tables:
            table = table_of(spec.model)
            columns = [c for c in table.columns if c.name not in spec.exclude]
            rows = await session.execute(select(*columns).where(spec.owner(user_id)))
            data[table.name] = [
                {key: jsonable(item) for key, item in row._mapping.items()} for row in rows
            ]
    if section.supplement is not None:
        more = await section.supplement(container, user_id)
        data |= {key: jsonable(item) for key, item in more.items()}
    return data


async def export_user_data(
    container: AsyncContainer,
    user_id: UUID,
    *,
    now: datetime,
    note: str | None = None,
    registry: PrivacyRegistry = PRIVACY,
) -> dict[str, Any]:
    """Данные пользователя всех модулей и запись об этом в audit_log."""
    sections = {
        name: await _section(container, section, user_id)
        for name, section in sorted(registry.sections.items())
    }
    async with container() as request:
        uow = await request.get(UnitOfWork)
        audit = await request.get(AuditLog)
        async with uow:
            await audit.record(
                AuditEntry(
                    action=EXPORTED,
                    actor_kind=ActorKind.STAFF,
                    entity_type="user",
                    entity_id=user_id,
                    changes={"sections": sorted(sections), "note": note},
                )
            )
    return {
        "format": EXPORT_FORMAT,
        "user_id": str(user_id),
        "exported_at": now.isoformat(),
        "sections": sections,
    }
