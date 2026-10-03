"""messaging_0001: диалоги, участники и сообщения (ARCHITECTURE §7.3, §11.5; DEVELOPMENT_PLAN 6.3a).

`messaging.conversations` — диалог по отклику (один на отклик, `uq_conversations_response_id`)
или прямой (один на пару клиент — специалист, частичный уникальный индекс); стороны — колонками
для этих проверок и в `participants` с прочитанным. `messaging.messages` — UUIDv7 задаёт
порядок; повтор `client_msg_id` автора не дублирует (`uq_messages_sender_id_client_msg_id`).
Обмен контактами — 6.3b. Таблицы новые и пустые — блокировок нет.

Ревизия: messaging_0001 (2026-10-02 20:30:00.000000+00:00)
Предыдущая: deals_0002

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

revision: str = "messaging_0001"
down_revision: str | Sequence[str] | None = "deals_0002"
branch_labels: str | Sequence[str] | None = ("messaging",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "messaging"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=15), server_default="open", nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("performer_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("response_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('job_response', 'direct', 'support')", name=op.f("ck_conversations_kind")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'blocked')", name=op.f("ck_conversations_status")
        ),
        sa.CheckConstraint("client_id <> performer_id", name=op.f("ck_conversations_two_parties")),
        sa.CheckConstraint(
            "kind <> 'job_response' OR response_id IS NOT NULL",
            name=op.f("ck_conversations_response_kind_refs"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["identity.users.id"], name=op.f("fk_conversations_client_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["performer_id"],
            ["identity.users.id"],
            name=op.f("fk_conversations_performer_id_users"),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.jobs.id"], name=op.f("fk_conversations_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["response_id"],
            ["jobs.responses.id"],
            name=op.f("fk_conversations_response_id_responses"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_conversations_deal_id_deals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("response_id", name=op.f("uq_conversations_response_id")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_conversations_direct_pair",
        "conversations",
        ["client_id", "performer_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("kind = 'direct'"),
    )
    op.create_table(
        "participants",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=17), nullable=False),
        sa.Column("last_read_message_id", sa.Uuid(), nullable=True),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('client', 'performer', 'support')", name=op.f("ck_participants_role")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["messaging.conversations.id"],
            name=op.f("fk_participants_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_participants_user_id_users")
        ),
        sa.PrimaryKeyConstraint("conversation_id", "user_id", name=op.f("pk_participants")),
        schema=SCHEMA,
    )
    op.create_index("ix_participants_user_id", "participants", ["user_id"], schema=SCHEMA)
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=True),
        sa.Column("client_msg_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=21), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'tma'"), nullable=False),
        sa.Column("moderation", sa.String(length=15), server_default="ok", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('text', 'media', 'system', 'contact_share', 'offer')",
            name=op.f("ck_messages_kind"),
        ),
        sa.CheckConstraint(
            "moderation IN ('ok', 'flagged', 'hidden')", name=op.f("ck_messages_moderation")
        ),
        sa.CheckConstraint("char_length(body) <= 4000", name=op.f("ck_messages_body_length")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["messaging.conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["identity.users.id"], name=op.f("fk_messages_sender_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media.assets.id"], name=op.f("fk_messages_media_id_assets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "sender_id", "client_msg_id", name=op.f("uq_messages_sender_id_client_msg_id")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_messages_conversation_id_id",
        "messages",
        ["conversation_id", sa.text("id DESC")],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("messages", schema=SCHEMA)
    op.drop_table("participants", schema=SCHEMA)
    op.drop_index("uq_conversations_direct_pair", table_name="conversations", schema=SCHEMA)
    op.drop_table("conversations", schema=SCHEMA)
