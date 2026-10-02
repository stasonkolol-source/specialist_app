"""search_0001: read-model поиска специалистов (ARCHITECTURE §7.3, §9.3; DEVELOPMENT_PLAN 4.1).

`specialist_index` — одна денормализованная строка на опубликованный профиль;
`specialist_category_prices` — цена «от» по категориям для фильтра «до N»; `pending_profiles` —
очередь пересборки: события отмечают профили, задача search.flush_index пересобирает пачку.
Индексы — набор лаборатории (research/07 §3.4, lab/sql/15), частичные `WHERE is_listed`.
FK на чужие схемы нет: строки пересобирает проектор по событиям. Схема search создана в
platform_0001. Таблицы новые и пустые — индексы без CONCURRENTLY.

Ревизия: search_0001 (2026-10-02 07:36:39.189729+00:00)
Предыдущая: identity_0004

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "search_0001"
down_revision: str | Sequence[str] | None = "identity_0004"
branch_labels: str | Sequence[str] | None = ("search",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"
LISTED = sa.text("is_listed")


def _point() -> geoalchemy2.Geography:
    return geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def _ints() -> postgresql.ARRAY:
    return postgresql.ARRAY(sa.Integer())


def upgrade() -> None:
    op.create_table(
        "specialist_index",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("district_ids", _ints(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("base_point", _point(), nullable=True),
        sa.Column("base_point_public", _point(), nullable=True),
        sa.Column("travel_radius_m", sa.Integer(), nullable=True),
        sa.Column("category_ids", _ints(), nullable=False),
        sa.Column("tag_ids", _ints(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("work_modes", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("price_from", sa.BigInteger(), nullable=True),
        sa.Column("rating_bayes", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rating_lower_bound", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rating_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "badges", postgresql.ARRAY(sa.String(length=32)), server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activity_score", sa.REAL(), server_default=sa.text("0"), nullable=False),
        sa.Column("score", sa.REAL(), server_default=sa.text("0"), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column("card", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_specialist_index")),
        schema=SCHEMA,
    )
    op.create_index("ix_specialist_index_user_id", "specialist_index", ["user_id"], schema=SCHEMA)
    for column in ("category_ids", "search_vector", "district_ids"):
        op.create_index(
            f"ix_specialist_index_{column}", "specialist_index", [column], schema=SCHEMA,
            postgresql_using="gin", postgresql_where=LISTED,
        )
    for column in ("base_point", "base_point_public"):
        op.create_index(
            f"ix_specialist_index_{column}", "specialist_index", [column], schema=SCHEMA,
            postgresql_using="gist",
            postgresql_where=sa.text(f"is_listed AND {column} IS NOT NULL"),
        )
    op.create_index(
        "ix_specialist_index_city_id_score", "specialist_index",
        ["city_id", sa.literal_column("score DESC"), sa.literal_column("profile_id DESC")],
        schema=SCHEMA, postgresql_where=LISTED,
    )
    op.create_index(
        "ix_specialist_index_name_norm", "specialist_index", ["name_norm"], schema=SCHEMA,
        postgresql_using="gist", postgresql_ops={"name_norm": "gist_trgm_ops"},
        postgresql_where=LISTED,
    )
    op.create_table(
        "specialist_category_prices",
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("price_from", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "category_id", "profile_id", name=op.f("pk_specialist_category_prices")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_specialist_category_prices_profile_id", "specialist_category_prices", ["profile_id"],
        schema=SCHEMA,
    )
    op.create_table(
        "pending_profiles",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "marked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_pending_profiles")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_pending_profiles_marked_at", "pending_profiles", ["marked_at"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("pending_profiles", schema=SCHEMA)
    op.drop_table("specialist_category_prices", schema=SCHEMA)
    op.drop_table("specialist_index", schema=SCHEMA)
