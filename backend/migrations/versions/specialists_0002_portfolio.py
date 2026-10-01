"""specialists_0002: портфолио и фото профиля (DEVELOPMENT_PLAN 2.11).

DDL портфолио — ARCHITECTURE §7.3 (`portfolio_items`, `portfolio_media`) плюс `kind` файла
работы: лимиты 60 фото и 6 роликов на профиль считаются без чтения схемы media. Фото
профиля — `profiles.avatar_media_id`: показывает его specialists (media ниже по DAG, identity —
нет). FK на catalog и media — вниз по DAG. Таблицы новые и пустые, колонка — nullable.

Ревизия: specialists_0002 (2026-10-01 15:37:18.040815+00:00)
Предыдущая: pricing_0001

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

revision: str = "specialists_0002"
down_revision: str | Sequence[str] | None = "pricing_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "specialists"


def upgrade() -> None:
    op.create_table(
        "portfolio_items",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=17), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'rejected')", name=op.f("ck_portfolio_items_status")
        ),
        sa.CheckConstraint("char_length(title) <= 120", name=op.f("ck_portfolio_items_title_length")),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["specialists.profiles.id"], name=op.f("fk_portfolio_items_profile_id_profiles")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["catalog.categories.id"], name=op.f("fk_portfolio_items_category_id_categories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_items")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_portfolio_items_profile_id", "portfolio_items", ["profile_id", "position"], unique=False,
        schema=SCHEMA, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "portfolio_media",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=13), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("kind IN ('image', 'video')", name=op.f("ck_portfolio_media_kind")),
        sa.ForeignKeyConstraint(
            ["item_id"], ["specialists.portfolio_items.id"], name=op.f("fk_portfolio_media_item_id_portfolio_items")
        ),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media.assets.id"], name=op.f("fk_portfolio_media_media_id_assets")
        ),
        sa.PrimaryKeyConstraint("item_id", "media_id", name=op.f("pk_portfolio_media")),
        schema=SCHEMA,
    )
    op.add_column("profiles", sa.Column("avatar_media_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        op.f("fk_profiles_avatar_media_id_assets"), "profiles", "assets",
        ["avatar_media_id"], ["id"], source_schema=SCHEMA, referent_schema="media",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_profiles_avatar_media_id_assets"), "profiles", schema=SCHEMA)
    op.drop_column("profiles", "avatar_media_id", schema=SCHEMA)
    op.drop_table("portfolio_media", schema=SCHEMA)
    op.drop_index(
        "ix_portfolio_items_profile_id", table_name="portfolio_items", schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("portfolio_items", schema=SCHEMA)
