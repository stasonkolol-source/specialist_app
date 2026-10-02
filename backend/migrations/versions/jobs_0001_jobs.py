"""jobs_0001: заявки, их фото и история статусов (ARCHITECTURE §7.3, §7.9; DEVELOPMENT_PLAN 5.1).

`jobs.jobs` — заявка клиента с жизненным циклом §7.9: точная точка и адрес — только выбранному
исполнителю, наружу — смещённая точка и район. `jobs.job_media` — фото по порядку.
`jobs.status_history` — переходы статусов (§7.10). Индексы ленты (5.3) — частичные
`WHERE status = 'published'`. Таблицы новые и пустые — блокировок нет.

Ревизия: jobs_0001 (2026-10-02 13:30:00.000000+00:00)
Предыдущая: search_0003

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

revision: str = "jobs_0001"
down_revision: str | Sequence[str] | None = "search_0003"
branch_labels: str | Sequence[str] | None = ("jobs",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"
PUBLISHED = sa.text("status = 'published'")


def _point() -> geoalchemy2.Geography:
    return geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=26), server_default="draft", nullable=False),
        sa.Column("visibility", sa.String(length=14), server_default="public", nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_lang", sa.String(length=8), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("category_path", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column(
            "tag_ids", postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("urgency", sa.String(length=17), nullable=False),
        sa.Column("preferred_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferred_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("budget_type", sa.String(length=18), nullable=False),
        sa.Column("budget_min", sa.BigInteger(), nullable=True),
        sa.Column("budget_max", sa.BigInteger(), nullable=True),
        sa.Column("budget_unit", sa.String(length=14), server_default="work", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RSD'"), nullable=False),
        sa.Column("verified_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("point_exact", _point(), nullable=True),
        sa.Column("point_public", _point(), nullable=True),
        sa.Column("address_private", sa.Text(), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(length=8)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("max_responses", sa.SmallInteger(), server_default=sa.text("5"), nullable=False),
        sa.Column("responses_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("extensions_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("views_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'tma'"), nullable=False),
        sa.Column("moderation_note", sa.String(length=64), nullable=True),
        sa.Column("selected_response_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=23), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_moderation', 'published', 'assigned', 'completed',"
            " 'closed', 'expired', 'rejected', 'removed')",
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint("visibility IN ('public', 'direct')", name=op.f("ck_jobs_visibility")),
        sa.CheckConstraint(
            "urgency IN ('asap', 'today', 'this_week', 'flexible')", name=op.f("ck_jobs_urgency")
        ),
        sa.CheckConstraint(
            "budget_type IN ('fixed', 'range', 'negotiable')", name=op.f("ck_jobs_budget_type")
        ),
        sa.CheckConstraint(
            "budget_unit IN ('work', 'hour', 'm2', 'visit', 'item', 'lesson')",
            name=op.f("ck_jobs_budget_unit"),
        ),
        sa.CheckConstraint(
            "close_reason IN ('hired_here', 'hired_elsewhere', 'not_needed', 'no_suitable',"
            " 'expired', 'removed')",
            name=op.f("ck_jobs_close_reason"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 5 AND 120", name=op.f("ck_jobs_title_length")
        ),
        sa.CheckConstraint(
            "char_length(description) <= 3000", name=op.f("ck_jobs_description_length")
        ),
        sa.CheckConstraint(
            "budget_type = 'negotiable' OR budget_min IS NOT NULL", name=op.f("ck_jobs_budget_set")
        ),
        sa.CheckConstraint("currency = 'RSD'", name=op.f("ck_jobs_currency_rsd")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["identity.users.id"], name=op.f("fk_jobs_client_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["catalog.categories.id"], name=op.f("fk_jobs_category_id_categories")
        ),
        sa.ForeignKeyConstraint(["city_id"], ["geo.cities.id"], name=op.f("fk_jobs_city_id_cities")),
        sa.ForeignKeyConstraint(
            ["district_id"], ["geo.districts.id"], name=op.f("fk_jobs_district_id_districts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jobs_client_id_created_at",
        "jobs",
        ["client_id", "created_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_jobs_city_id_published_at",
        "jobs",
        ["city_id", "published_at", "id"],
        schema=SCHEMA,
        postgresql_where=PUBLISHED,
    )
    op.create_index(
        "ix_jobs_expires_at", "jobs", ["expires_at"], schema=SCHEMA, postgresql_where=PUBLISHED
    )

    op.create_table(
        "job_media",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.jobs.id"], name=op.f("fk_job_media_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media.assets.id"], name=op.f("fk_job_media_media_id_assets")
        ),
        sa.PrimaryKeyConstraint("job_id", "media_id", name=op.f("pk_job_media")),
        schema=SCHEMA,
    )

    op.create_table(
        "status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=17), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'moderator', 'system')", name=op.f("ck_status_history_actor_kind")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.jobs.id"], name=op.f("fk_status_history_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_history")),
        schema=SCHEMA,
    )
    op.create_index("ix_status_history_job_id", "status_history", ["job_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("status_history", schema=SCHEMA)
    op.drop_table("job_media", schema=SCHEMA)
    op.drop_table("jobs", schema=SCHEMA)
