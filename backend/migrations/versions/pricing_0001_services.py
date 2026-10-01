"""pricing_0001: прайс исполнителя (ARCHITECTURE §7.3 `pricing.services`, DEVELOPMENT_PLAN 2.8b).

DDL архитектуры плюс `category_id` — группа позиций в S35. Цена — пара (1 RSD = 100 пара),
только RSD (CHECK); у всех типов, кроме договорной, есть цена; у диапазона максимум не меньше
минимума. FK на specialists.profiles и catalog.categories — вниз по DAG. Таблица новая и пустая.

Ревизия: pricing_0001 (2026-10-01 16:00:00.000000+00:00)
Предыдущая: specialists_0001

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

revision: str = "pricing_0001"
down_revision: str | Sequence[str] | None = "specialists_0001"
branch_labels: str | Sequence[str] | None = ("pricing",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "pricing"


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_type", sa.String(length=18), nullable=False),
        sa.Column("price_min", sa.BigInteger(), nullable=True),
        sa.Column("price_max", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RSD", nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "price_type IN ('fixed', 'from', 'range', 'hourly', 'per_unit', 'negotiable')",
            name=op.f("ck_services_price_type"),
        ),
        sa.CheckConstraint("currency = 'RSD'", name=op.f("ck_services_currency_rsd")),
        sa.CheckConstraint(
            "price_type = 'negotiable' OR price_min IS NOT NULL", name=op.f("ck_services_price_set")
        ),
        sa.CheckConstraint(
            "price_max IS NULL OR price_max >= price_min", name=op.f("ck_services_price_range")
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["specialists.profiles.id"], name=op.f("fk_services_profile_id_profiles")),
        sa.ForeignKeyConstraint(["category_id"], ["catalog.categories.id"], name=op.f("fk_services_category_id_categories")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_services_profile_id_position", "services", ["profile_id", "position"], unique=False,
        schema=SCHEMA, postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("services", schema=SCHEMA)
