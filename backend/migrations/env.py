"""Окружение Alembic (DEVELOPMENT_PLAN 0.9): async, роль migrator, схема на модуль.

- Таблица версий — `platform.alembic_version`: в `public` не может создавать никто, кроме
  суперпользователя (infra/postgres/bootstrap.sql).
- `alembic check` видит только схемы модулей: Procrastinate и объекты PostGIS исключены.
- FK на таблицу другой схемы (`identity.users.home_city_id` → `geo.cities`) пишется в
  миграции руками: MetaData модуля чужих таблиц не знает (ORM-ForeignKey на них не
  разрешится при flush), поэтому такие FK в базе autogenerate не сравнивает.
"""

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import ForeignKeyConstraint, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.entrypoints._metadata import module_metadatas
from app.platform.db.registry import EXCLUDED_SCHEMAS, MODULE_SCHEMAS
from app.platform.settings import DbSettings

VERSION_SCHEMA = "platform"
config = context.config
target_metadata = module_metadatas()


def _migrator_dsn() -> str:
    settings = DbSettings()  # type: ignore[call-arg]  # значения — из окружения и backend/.env
    if settings.migrator_dsn is None:
        raise RuntimeError("DB_MIGRATOR_DSN is not set: migrations run as role migrator")
    return settings.migrator_dsn.get_secret_value()


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    if type_ == "schema":
        return name in MODULE_SCHEMAS
    if type_ == "table" and parent_names.get("schema_name") in EXCLUDED_SCHEMAS:
        return False
    return not (type_ == "table" and name == "alembic_version")


def include_object(
    obj: Any,
    _name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001 — сигнатуру хука задаёт Alembic
    _compare_to: Any,
) -> bool:
    """FK из базы на таблицу другой схемы — только в миграциях, в моделях его нет."""
    if type_ == "foreign_key_constraint" and reflected and isinstance(obj, ForeignKeyConstraint):
        target = obj.elements[0].target_fullname.split(".")
        return not (len(target) == 3 and target[0] != obj.table.schema)
    return True


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=VERSION_SCHEMA,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
    )


def _run_sync(connection: Connection) -> None:
    # Таблица версий живёт в platform — схема нужна до первой миграции.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {VERSION_SCHEMA}"))
    connection.commit()
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_migrator_dsn(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


def run_offline() -> None:
    context.configure(
        url=_migrator_dsn(),
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=VERSION_SCHEMA,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
