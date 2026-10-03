"""reviews_0002: отзывы по сделкам (ARCHITECTURE §7.3, §7.9; DEVELOPMENT_PLAN 7.2).

`reviews.reviews` — отзыв клиента об исполнителе по завершённой сделке: оценка, критерии, текст,
проверка (`under_review` → `published` / `removed`), один ответ исполнителя со своей проверкой.
Один отзыв автора на сделку — частичный уникальный индекс. Отступления от §7.3: `category_id` —
снимок категории сделки для априорного среднего рейтинга, `reply_status` — ответ проверяется
отдельно, `version` — optimistic locking агрегата. `rating_aggregates.last_published_at` — дата
последнего отзыва рядом с рейтингом (ADR-0016). Таблица новая, колонка nullable — блокировок нет.

Ревизия: reviews_0002 (2026-10-03 00:50:00.000000+00:00)
Предыдущая: search_0004

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
from sqlalchemy.dialects import postgresql

revision: str = "reviews_0002"
down_revision: str | Sequence[str] | None = "search_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "reviews"


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("kind", sa.String(length=20), server_default="deal", nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_profile_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=27), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column(
            "criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="under_review", nullable=False),
        sa.Column("reply_body", sa.Text(), nullable=True),
        sa.Column("reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_status", sa.String(length=20), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('deal', 'pre_platform')", name=op.f("ck_reviews_kind")),
        sa.CheckConstraint(
            "direction IN ('client_to_performer', 'performer_to_client')",
            name=op.f("ck_reviews_direction"),
        ),
        sa.CheckConstraint(
            "status IN ('hidden', 'under_review', 'published', 'removed')",
            name=op.f("ck_reviews_status"),
        ),
        sa.CheckConstraint(
            "reply_status IN ('under_review', 'published', 'removed')",
            name=op.f("ck_reviews_reply_status"),
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_reviews_rating_range")),
        sa.CheckConstraint("char_length(body) <= 2000", name=op.f("ck_reviews_body_length")),
        sa.CheckConstraint(
            "char_length(reply_body) <= 2000", name=op.f("ck_reviews_reply_body_length")
        ),
        sa.CheckConstraint(
            "kind = 'pre_platform' OR deal_id IS NOT NULL",
            name=op.f("ck_reviews_deal_review_has_deal"),
        ),
        sa.CheckConstraint(
            "(reply_body IS NULL) = (reply_status IS NULL)"
            " AND (reply_body IS NULL) = (reply_at IS NULL)",
            name=op.f("ck_reviews_reply_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_reviews_deal_id_deals")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["identity.users.id"], name=op.f("fk_reviews_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["identity.users.id"],
            name=op.f("fk_reviews_subject_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_profile_id"],
            ["specialists.profiles.id"],
            name=op.f("fk_reviews_subject_profile_id_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_reviews_deal_id_author_id",
        "reviews",
        ["deal_id", "author_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deal_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_reviews_subject_profile_id_published_at",
        "reviews",
        ["subject_profile_id", sa.text("published_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index("ix_reviews_author_id", "reviews", ["author_id"], schema=SCHEMA)
    op.create_index("ix_reviews_subject_user_id", "reviews", ["subject_user_id"], schema=SCHEMA)
    op.add_column(
        "rating_aggregates",
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("rating_aggregates", "last_published_at", schema=SCHEMA)
    op.drop_index("ix_reviews_subject_user_id", table_name="reviews", schema=SCHEMA)
    op.drop_index("ix_reviews_author_id", table_name="reviews", schema=SCHEMA)
    op.drop_index("ix_reviews_subject_profile_id_published_at", table_name="reviews", schema=SCHEMA)
    op.drop_index("uq_reviews_deal_id_author_id", table_name="reviews", schema=SCHEMA)
    op.drop_table("reviews", schema=SCHEMA)
