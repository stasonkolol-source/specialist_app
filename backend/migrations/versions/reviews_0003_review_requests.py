"""reviews_0003: просьбы оставить отзыв (ARCHITECTURE §7.9, §12.3; DEVELOPMENT_PLAN 7.2).

`reviews.review_requests` — по строке на завершённую сделку: клиенту ушёл `review.request`,
`reviews.reminders` напоминает через сутки и за 2 дня до конца окна в 14 дней, пока отзыва нет.
Таблица новая — блокировок нет.

Ревизия: reviews_0003 (2026-10-03 01:20:00.000000+00:00)
Предыдущая: moderation_0003

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

revision: str = "reviews_0003"
down_revision: str | Sequence[str] | None = "moderation_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "reviews"


def upgrade() -> None:
    op.create_table(
        "review_requests",
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("performer_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_call_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_review_requests_deal_id_deals")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["identity.users.id"], name=op.f("fk_review_requests_client_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["performer_id"],
            ["identity.users.id"],
            name=op.f("fk_review_requests_performer_id_users"),
        ),
        sa.PrimaryKeyConstraint("deal_id", name=op.f("pk_review_requests")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_review_requests_completed_at",
        "review_requests",
        ["completed_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("last_call_at IS NULL"),
    )
    op.create_index("ix_review_requests_client_id", "review_requests", ["client_id"], schema=SCHEMA)
    op.create_index(
        "ix_review_requests_performer_id", "review_requests", ["performer_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_review_requests_performer_id", table_name="review_requests", schema=SCHEMA)
    op.drop_index("ix_review_requests_client_id", table_name="review_requests", schema=SCHEMA)
    op.drop_index("ix_review_requests_completed_at", table_name="review_requests", schema=SCHEMA)
    op.drop_table("review_requests", schema=SCHEMA)
