"""specialists_0001: профили исполнителей, категории, районы выезда (DEVELOPMENT_PLAN 2.8a).

DDL — ARCHITECTURE §7.3 плюс `is_founding` (§15.2), `pro_waitlist_at` (Q24),
`rejection_reason` и `reviewed_kind` (возврат на правки и повторная проверка «Подработка →
Специалист»), `submitted_at`. Один живой профиль на пользователя — `uq_profiles_user_id_alive`.
Портфолио — шаг 2.11, рабочие часы — v1. FK на identity, geo и catalog — вниз по DAG.
Схема specialists создана в platform_0001. Таблицы новые и пустые.

Ревизия: specialists_0001 (2026-10-01 15:05:00.000000+00:00)
Предыдущая: notifications_0004

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

revision: str = "specialists_0001"
down_revision: str | Sequence[str] | None = "notifications_0004"
branch_labels: str | Sequence[str] | None = ("specialists",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "specialists"


def _point() -> geoalchemy2.Geography:
    return geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("status", sa.String(length=22), server_default="draft", nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("content_lang", sa.String(length=8), nullable=True),
        sa.Column("experience_since", sa.SmallInteger(), nullable=True),
        sa.Column("languages", postgresql.ARRAY(sa.String(length=8)), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("base_point", _point(), nullable=True),
        sa.Column("base_point_public", _point(), nullable=True),
        sa.Column("travel_radius_km", sa.SmallInteger(), nullable=True),
        sa.Column("work_modes", postgresql.ARRAY(sa.String(length=16)), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vacation_until", sa.Date(), nullable=True),
        sa.Column("trader_status", sa.String(length=16), nullable=True),
        sa.Column("registry_id", sa.Text(), nullable=True),
        sa.Column("business_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("listed_in_catalog", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_founding", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("pro_waitlist_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=64), nullable=True),
        sa.Column("reviewed_kind", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('pro', 'casual')", name=op.f("ck_profiles_kind")),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'hidden', 'suspended')",
            name=op.f("ck_profiles_status"),
        ),
        sa.CheckConstraint("char_length(headline) <= 80", name=op.f("ck_profiles_headline_length")),
        sa.CheckConstraint("char_length(about) <= 4000", name=op.f("ck_profiles_about_length")),
        sa.CheckConstraint("travel_radius_km IN (3, 5, 10)", name=op.f("ck_profiles_travel_radius")),
        sa.CheckConstraint("trader_status IN ('trader', 'non_trader')", name=op.f("ck_profiles_trader_status")),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_profiles_user_id_users")),
        sa.ForeignKeyConstraint(["city_id"], ["geo.cities.id"], name=op.f("fk_profiles_city_id_cities")),
        sa.ForeignKeyConstraint(["district_id"], ["geo.districts.id"], name=op.f("fk_profiles_district_id_districts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_profiles_user_id_alive", "profiles", ["user_id"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_profiles_status_city_id", "profiles", ["status", "city_id"], unique=False, schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_profiles_slug", "profiles", ["slug"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text("slug IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_table(
        "profile_categories",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["specialists.profiles.id"], name=op.f("fk_profile_categories_profile_id_profiles")),
        sa.ForeignKeyConstraint(["category_id"], ["catalog.categories.id"], name=op.f("fk_profile_categories_category_id_categories")),
        sa.PrimaryKeyConstraint("profile_id", "category_id", name=op.f("pk_profile_categories")),
        schema=SCHEMA,
    )
    op.create_table(
        "service_areas",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["specialists.profiles.id"], name=op.f("fk_service_areas_profile_id_profiles")),
        sa.ForeignKeyConstraint(["district_id"], ["geo.districts.id"], name=op.f("fk_service_areas_district_id_districts")),
        sa.PrimaryKeyConstraint("profile_id", "district_id", name=op.f("pk_service_areas")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("service_areas", schema=SCHEMA)
    op.drop_table("profile_categories", schema=SCHEMA)
    op.drop_table("profiles", schema=SCHEMA)
