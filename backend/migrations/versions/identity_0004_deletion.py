"""identity_0004: удаление аккаунта по запросу (DEVELOPMENT_PLAN 2.12a, ARCHITECTURE §7.10).

- `deletion_requests` — запрос с grace-периодом 7 дней: у пользователя не больше одного ждущего
  (частичный уникальный индекс), ждущие по сроку — для ежечасного `identity.process_deletions`.
- `deleted_identity_hashes` — HMAC Telegram ID и телефона удалённых аккаунтов на 12 месяцев:
  повторная регистрация — сигнал риска.

Таблицы новые и пустые, на живые таблицы миграция не влияет.

Ревизия: identity_0004 (2026-10-01 18:00:00.000000+00:00)
Предыдущая: specialists_0002

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "identity_0004"
down_revision: str | Sequence[str] | None = "specialists_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"
ACTIVE = sa.text("cancelled_at IS NULL AND completed_at IS NULL")


def upgrade() -> None:
    op.create_table(
        "deletion_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=15), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('tma', 'bot', 'ios', 'android', 'web', 'support')",
            name=op.f("ck_deletion_requests_source"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_deletion_requests_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_requests")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_deletion_requests_user_id_active", "deletion_requests", ["user_id"], unique=True,
        schema=SCHEMA, postgresql_where=ACTIVE,
    )
    op.create_index(
        "ix_deletion_requests_execute_after", "deletion_requests", ["execute_after"], unique=False,
        schema=SCHEMA, postgresql_where=ACTIVE,
    )
    op.create_table(
        "deleted_identity_hashes",
        sa.Column("hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("had_sanctions", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('telegram', 'phone')", name=op.f("ck_deleted_identity_hashes_kind")
        ),
        sa.PrimaryKeyConstraint("hash", name=op.f("pk_deleted_identity_hashes")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("deleted_identity_hashes", schema=SCHEMA)
    op.drop_index(
        "ix_deletion_requests_execute_after", table_name="deletion_requests", schema=SCHEMA,
        postgresql_where=ACTIVE,
    )
    op.drop_index(
        "uq_deletion_requests_user_id_active", table_name="deletion_requests", schema=SCHEMA,
        postgresql_where=ACTIVE,
    )
    op.drop_table("deletion_requests", schema=SCHEMA)
