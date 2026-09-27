"""Реестр схем и MetaData модулей для Alembic (DEVELOPMENT_PLAN 0.9).

Модуль, у которого появились ORM-модели, добавляет свою MetaData в `module_metadatas()`
в том же шаге: иначе `alembic check` не увидит его таблицы.
"""

from sqlalchemy import MetaData

MODULE_SCHEMAS: tuple[str, ...] = (
    "platform",
    "identity",
    "geo",
    "catalog",
    "media",
    "billing",
    "specialists",
    "pricing",
    "deals",
    "jobs",
    "messaging",
    "reviews",
    "search",
    "growth",
    "notifications",
    "moderation",
)
"""Схемы MVP (ARCHITECTURE §7.1). goods — после MVP (ADR-0019)."""

EXCLUDED_SCHEMAS: frozenset[str] = frozenset({"procrastinate", "public", "topology", "tiger"})
"""Не наши объекты: Procrastinate управляет своей схемой, PostGIS — public/topology/tiger."""


def module_metadatas() -> list[MetaData]:
    """MetaData всех модулей с таблицами. Пока таблиц нет — список пуст."""
    return []
