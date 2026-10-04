"""reviews_0004: «отзывы до платформы» по приглашению (ARCHITECTURE §7.3; DEVELOPMENT_PLAN 7.6а).

`reviews.review_invites` — ссылки специалиста прошлым клиентам: не больше пяти занятых мест на
профиль (проверка в приложении), 30 дней, один отзыв по ссылке. Отступления от §7.3: `token` —
uuid (случайный v4: ссылка `ri_<base62>` тем же кодеком, что у сущностей), `client_name` —
кому отправлена (заметка для S55), `review_id` — отзыв по ссылке. У `reviews.reviews` —
`work_title` («что делал мастер», S56) и один отзыв до платформы от человека на профиль
(частичный уникальный индекс). Таблица новая; колонка — nullable без default, CHECK — NOT VALID
с отдельной проверкой, индекс — CONCURRENTLY: долгих блокировок нет.

Ревизия: reviews_0004 (2026-10-04 12:00:00.000000+00:00)
Предыдущая: platform_0005

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

revision: str = "reviews_0004"
down_revision: str | Sequence[str] | None = "platform_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "reviews"
UNIQUE_PRE_PLATFORM = "uq_reviews_subject_profile_id_author_id"


def upgrade() -> None:
    op.add_column("reviews", sa.Column("work_title", sa.Text(), nullable=True), schema=SCHEMA)
    op.execute(
        "ALTER TABLE reviews.reviews ADD CONSTRAINT ck_reviews_work_title_length"
        " CHECK (char_length(work_title) <= 120) NOT VALID"
    )
    op.execute("ALTER TABLE reviews.reviews VALIDATE CONSTRAINT ck_reviews_work_title_length")
    op.create_table(
        "review_invites",
        sa.Column("token", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "char_length(client_name) <= 60", name=op.f("ck_review_invites_client_name_length")
        ),
        sa.CheckConstraint(
            "(used_by IS NULL) = (used_at IS NULL) AND (used_by IS NULL) = (review_id IS NULL)",
            name=op.f("ck_review_invites_use_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["specialists.profiles.id"],
            name=op.f("fk_review_invites_profile_id_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["used_by"], ["identity.users.id"], name=op.f("fk_review_invites_used_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.reviews.id"],
            name=op.f("fk_review_invites_review_id_reviews"),
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_review_invites")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_review_invites_profile_id",
        "review_invites",
        ["profile_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )
    op.create_index("ix_review_invites_used_by", "review_invites", ["used_by"], schema=SCHEMA)
    with op.get_context().autocommit_block():
        op.create_index(
            UNIQUE_PRE_PLATFORM,
            "reviews",
            ["subject_profile_id", "author_id"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("kind = 'pre_platform' AND deleted_at IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            UNIQUE_PRE_PLATFORM,
            table_name="reviews",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_index("ix_review_invites_used_by", table_name="review_invites", schema=SCHEMA)
    op.drop_index("ix_review_invites_profile_id", table_name="review_invites", schema=SCHEMA)
    op.drop_table("review_invites", schema=SCHEMA)
    op.execute("ALTER TABLE reviews.reviews DROP CONSTRAINT ck_reviews_work_title_length")
    op.drop_column("reviews", "work_title", schema=SCHEMA)
