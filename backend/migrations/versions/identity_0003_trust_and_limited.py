"""identity_0003: лимиты новичка и отсчёт нарушений для уровня доверия (DEVELOPMENT_PLAN 2.5a).

- `restrictions.kind` += `limited` — страйк 1 (ADR-0016 §4: «лимиты на 7 дней»). Новый CHECK —
  надмножество старого, длина varchar (26) не меняется. DROP → ADD … NOT VALID → VALIDATE
  после commit, как в media_0003. Откат с записями `limited` не пройдёт — их надо снять.
- `users.trust_penalty_at` — последнее нарушение (санкция или подтверждённая жалоба): от него
  считаются «14 дней без жалоб» уровня 1 (ADR-0016 §2). Колонка nullable, без значения.
- `ix_users_trust_aging` — кандидаты ежедневного `identity.trust_aging` (уровень 0),
  CONCURRENTLY: таблица живая.

Ревизия: identity_0003 (2026-09-30 21:00:00.000000+00:00)
Предыдущая: moderation_0001

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

revision: str = "identity_0003"
down_revision: str | Sequence[str] | None = "moderation_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "identity.restrictions"
CHECK = "ck_restrictions_kind"
OLD = "'posting_blocked', 'responding_blocked', 'messaging_blocked', 'shadow_banned', 'suspended', 'banned'"
NEW = f"'limited', {OLD}"


def _kinds(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (kind IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _kinds(NEW)
    op.add_column(
        "users",
        sa.Column("trust_penalty_at", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_users_trust_aging",
            "users",
            ["created_at"],
            unique=False,
            schema="identity",
            postgresql_where=sa.text("trust_level = 0"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_users_trust_aging",
            table_name="users",
            schema="identity",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("users", "trust_penalty_at", schema="identity")
    _kinds(OLD)
