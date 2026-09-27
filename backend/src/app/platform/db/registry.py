"""Реестр схем модулей для Alembic (DEVELOPMENT_PLAN 0.9).

MetaData модулей собирает `app/entrypoints/_metadata.py`: platform модулей не видит.
"""

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
