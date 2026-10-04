"""notifications_0008: рассылки из админки (DEVELOPMENT_PLAN 2.7b).

`notifications.broadcasts` — текст по языкам, кнопка, аудитория, статус и курсор разбора
получателей; таблица новая и пустая. Уведомлению — тип `broadcast` и приоритет P4 (рассылки
уходят после всего остального): новые CHECK — надмножества старых, длина varchar не меняется,
DROP → ADD … NOT VALID → VALIDATE после commit, как в notifications_0006. Частичный индекс по
префиксу ключа `broadcast:<id>:` — счётчики и отмена рассылки; на живой таблице —
CONCURRENTLY. Downgrade удаляет уведомления рассылок.

Ревизия: notifications_0008 (2026-10-04 18:00:00.000000+00:00)
Предыдущая: identity_0007

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

revision: str = "notifications_0008"
down_revision: str | Sequence[str] | None = "identity_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "notifications"
TABLE = "notifications.notifications"
TYPES_OLD = (
    "'job.matched', 'job.digest', 'response.received', 'response.accepted',"
    " 'response.not_selected', 'job.invited', 'message.received', 'deal.proposed',"
    " 'deal.cancelled', 'dispute.opened', 'dispute.resolved', 'deal.reminder',"
    " 'deal.completion_prompt', 'review.request', 'review.published', 'moderation.decision',"
    " 'job.expiring', 'job.expired', 'profile.stale_reminder', 'profile.published',"
    " 'account.restricted', 'system.test'"
)
TYPES_NEW = f"{TYPES_OLD}, 'broadcast'"
GROUPS = "'job_matches', 'responses', 'messages', 'deals', 'marketing', 'goods_launch', 'account'"


def _check(name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} CHECK ({condition}) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("status", sa.String(length=17), nullable=False),
        sa.Column("event_group", sa.String(length=20), nullable=False),
        sa.Column("audience", sa.String(length=19), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("text", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("link", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'sending', 'done', 'cancelled')",
            name=op.f("ck_broadcasts_status"),
        ),
        sa.CheckConstraint(f"event_group IN ({GROUPS})", name=op.f("ck_broadcasts_event_group")),
        sa.CheckConstraint(
            "event_group IN ('marketing', 'goods_launch')", name=op.f("ck_broadcasts_opt_in_group")
        ),
        sa.CheckConstraint(
            "audience IN ('all', 'specialists', 'clients', 'founding')",
            name=op.f("ck_broadcasts_audience"),
        ),
        sa.CheckConstraint("action IN ('pro_waitlist')", name=op.f("ck_broadcasts_action")),
        sa.CheckConstraint("link IS NULL OR action IS NULL", name=op.f("ck_broadcasts_one_button")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["identity.users.id"], name=op.f("fk_broadcasts_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcasts")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_broadcasts_created_at", "broadcasts", ["created_at"], unique=False, schema=SCHEMA
    )
    _check("ck_notifications_type", f"type IN ({TYPES_NEW})")
    _check("ck_notifications_priority", "priority BETWEEN 0 AND 4")
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_notifications_broadcast",
            "notifications",
            ["dedupe_key"],
            unique=False,
            schema=SCHEMA,
            postgresql_ops={"dedupe_key": "text_pattern_ops"},
            postgresql_where=sa.text("type = 'broadcast'"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_notifications_broadcast",
            table_name="notifications",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.execute(
        "DELETE FROM notifications.deliveries WHERE notification_id IN"
        " (SELECT id FROM notifications.notifications WHERE type = 'broadcast')"
    )
    op.execute("DELETE FROM notifications.notifications WHERE type = 'broadcast'")
    _check("ck_notifications_priority", "priority BETWEEN 0 AND 3")
    _check("ck_notifications_type", f"type IN ({TYPES_OLD})")
    op.drop_index("ix_broadcasts_created_at", table_name="broadcasts", schema=SCHEMA)
    op.drop_table("broadcasts", schema=SCHEMA)
