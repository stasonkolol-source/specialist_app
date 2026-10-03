"""jobs_0010: подписки на новые заявки и их совпадения с заявками (DEVELOPMENT_PLAN 5.7; §7.3, §9.6).

- `jobs.alerts` — подписка исполнителя (S18, S19): категории (выбранные узлы каталога), город,
  районы или точка с радиусом, бюджет «от», срочности, языки, «сразу / подборкой», выключатель и
  пауза из бота. Отличие от схемы §7.3: круга `area` нет — радиус проверяет `ST_DWithin` по
  центру с константным потолком 30 км (ADR-0006 п. 9, как «выезжает ко мне»): GiST по `center`
  участвует в плане, а полигон не нужно пересчитывать при правке.
- `jobs.alert_matches` — заявка подошла человеку: одна строка на пару, сразу (B1 поставлен) или
  подборкой (ждёт `jobs.alert_digests`); по ним — лимит частоты B1 и `notified_count`.
- `jobs.jobs.notified_count` — скольким подписчикам подошла заявка (S21, S23).
- `ix_jobs_city_id_published_at_any` — «N заявок за неделю» S18: заявки города, опубликованные
  за неделю, в том числе уже закрытые (частичный индекс ленты их не покрывает).

Таблицы новые — их индексы без CONCURRENTLY; индекс на живой jobs.jobs — CONCURRENTLY; колонка с
константным DEFAULT добавляется без переписывания таблицы.

Ревизия: jobs_0010 (2026-10-03 21:00:00.000000+00:00)
Предыдущая: moderation_0005

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

revision: str = "jobs_0010"
down_revision: str | Sequence[str] | None = "moderation_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"
JOBS_INDEX = "ix_jobs_city_id_published_at_any"


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("notified_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column(
            "district_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "center",
            geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("radius_m", sa.Integer(), nullable=True),
        sa.Column("min_budget", sa.BigInteger(), nullable=True),
        sa.Column(
            "urgencies",
            postgresql.ARRAY(sa.String(length=16)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(length=8)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "delivery",
            sa.String(length=15),
            server_default=sa.text("'instant'"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("delivery IN ('instant', 'digest')", name=op.f("ck_alerts_delivery")),
        sa.CheckConstraint("radius_m BETWEEN 500 AND 30000", name=op.f("ck_alerts_radius_range")),
        sa.CheckConstraint(
            "(center IS NULL) = (radius_m IS NULL)", name=op.f("ck_alerts_radius_with_center")
        ),
        sa.CheckConstraint(
            "cardinality(district_ids) = 0 OR center IS NULL",
            name=op.f("ck_alerts_districts_or_radius"),
        ),
        sa.CheckConstraint("cardinality(category_ids) > 0", name=op.f("ck_alerts_has_categories")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_alerts_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["city_id"], ["geo.cities.id"], name=op.f("fk_alerts_city_id_cities")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        schema=SCHEMA,
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"], schema=SCHEMA)
    op.create_index(
        "ix_alerts_category_ids",
        "alerts",
        ["category_ids"],
        schema=SCHEMA,
        postgresql_using="gin",
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_alerts_center",
        "alerts",
        ["center"],
        schema=SCHEMA,
        postgresql_using="gist",
        postgresql_where=sa.text("is_active AND center IS NOT NULL"),
    )
    op.create_table(
        "alert_matches",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("delivery", sa.String(length=15), nullable=False),
        _timestamp("created_at"),
        sa.Column("digested_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "delivery IN ('instant', 'digest')", name=op.f("ck_alert_matches_delivery")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.jobs.id"], name=op.f("fk_alert_matches_job_id_jobs")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_alert_matches_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["jobs.alerts.id"],
            name=op.f("fk_alert_matches_alert_id_alerts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "user_id", name=op.f("pk_alert_matches")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_alert_matches_user_id_created_at",
        "alert_matches",
        ["user_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_alert_matches_alert_id", "alert_matches", ["alert_id"], schema=SCHEMA)
    op.create_index(
        "ix_alert_matches_pending",
        "alert_matches",
        ["user_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("delivery = 'digest' AND digested_at IS NULL"),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            JOBS_INDEX,
            "jobs",
            ["city_id", "published_at"],
            schema=SCHEMA,
            postgresql_where=sa.text("published_at IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            JOBS_INDEX,
            table_name="jobs",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_table("alert_matches", schema=SCHEMA)
    op.drop_table("alerts", schema=SCHEMA)
    op.drop_column("jobs", "notified_count", schema=SCHEMA)
