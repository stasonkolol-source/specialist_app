"""messaging_0002: обмен контактами и сделка диалога (ARCHITECTURE §7.3, §11.5; DEVELOPMENT_PLAN 6.3b).

`messaging.contact_shares` — сторона поделилась контактом по сделке (по разу на вид контакта);
сам контакт — в сообщении `contact_share`, строка ссылается на него. Индекс диалога по сделке —
для подписчиков DealAgreed и DealCancelled; ключ системного сообщения (`<событие>:<сделка>` в
`client_msg_id` без автора) уникален в диалоге — повтор задачи второго не запишет. Индексы на
живых таблицах — CONCURRENTLY.

Ревизия: messaging_0002 (2026-10-02 23:10:00.000000+00:00)
Предыдущая: messaging_0001

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

revision: str = "messaging_0002"
down_revision: str | Sequence[str] | None = "messaging_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "messaging"


def upgrade() -> None:
    op.create_table(
        "contact_shares",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("shared_by", sa.Uuid(), nullable=False),
        sa.Column("shared_with", sa.Uuid(), nullable=False),
        sa.Column("contact_type", sa.String(length=16), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "contact_type IN ('telegram', 'phone')", name=op.f("ck_contact_shares_contact_type")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["messaging.conversations.id"],
            name=op.f("fk_contact_shares_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_contact_shares_deal_id_deals")
        ),
        sa.ForeignKeyConstraint(
            ["shared_by"], ["identity.users.id"], name=op.f("fk_contact_shares_shared_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["shared_with"], ["identity.users.id"], name=op.f("fk_contact_shares_shared_with_users")
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messaging.messages.id"],
            name=op.f("fk_contact_shares_message_id_messages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_shares")),
        sa.UniqueConstraint(
            "deal_id",
            "shared_by",
            "contact_type",
            name="uq_contact_shares_deal_id_shared_by_contact_type",
        ),
        schema=SCHEMA,
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_conversations_deal_id",
            "conversations",
            ["deal_id"],
            unique=False,
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "uq_messages_system_key",
            "messages",
            ["conversation_id", "client_msg_id"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("sender_id IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table in (
            ("uq_messages_system_key", "messages"),
            ("ix_conversations_deal_id", "conversations"),
        ):
            op.drop_index(
                name,
                table_name=table,
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_exists=True,
            )
    op.drop_table("contact_shares", schema=SCHEMA)
