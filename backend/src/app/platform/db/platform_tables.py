"""Таблицы схемы platform (миграция platform_0002, ARCHITECTURE §7.3, §7.10).

Core-таблицы без ORM: их пишут только адаптеры platform через свои порты, всегда внутри
UoW (ADR-0020 §4). Агрегатов тут нет.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB

from app.platform.db.base import module_metadata

metadata = module_metadata("platform")

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("user_id", Uuid, nullable=False),
    Column("key", String(255), nullable=False),
    Column("request_hash", LargeBinary(32), nullable=False),
    Column("status_code", Integer),
    Column("response", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("user_id", "key"),
    Index("ix_idempotency_keys_created_at", "created_at"),
)
"""status_code IS NULL — запрос в работе; ответ хранится 24 ч (platform.idempotency_cleanup)."""

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("actor_id", Uuid),
    Column("actor_kind", String(16), nullable=False),
    Column("action", String(128), nullable=False),
    Column("entity_type", String(64)),
    Column("entity_id", Uuid),
    Column("changes", JSONB),
    Column("ip", INET),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_audit_log_entity", "entity_type", "entity_id", text("created_at DESC")),
)
"""Только добавление: у роли app нет UPDATE и DELETE, UPDATE запрещён триггером."""

client_config = Table(
    "client_config",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_by", Uuid),
)
"""Конфигурация клиентов (GET /client-config): min_versions, legal_versions, … — правит админка.
`updated_by` — сотрудник, менявший последним (platform_0006); NULL — миграция или SQL."""

feature_flags = Table(
    "feature_flags",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("enabled", Boolean, nullable=False, server_default=text("false")),
    Column("value", JSONB),
    Column("public", Boolean, nullable=False, server_default=text("false")),
    Column("description", Text, nullable=False, server_default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_by", Uuid),
)
"""Флаги `<модуль>.<флаг>`; public — уходят клиенту в client-config, остальные — только backend.
`updated_by` — сотрудник, переключавший последним (platform_0006); NULL — миграция или SQL."""
