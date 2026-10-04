"""deals_0004: сделки диалога — по индексу (контакты остаются открытыми, ADR-0010, 2026-10-04).

Переписка спрашивает, договаривались ли стороны в диалоге хоть раз: сделка с этим
`conversation_id` и `agreed_at`. Раньше по `conversation_id` не искали — индекса не было. Частичный
(`conversation_id IS NOT NULL`): у сделок по отклику диалог не записан. Индекс — CONCURRENTLY.

Ревизия: deals_0004 (2026-10-04 21:00:00.000000+00:00)
Предыдущая: moderation_0009

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

revision: str = "deals_0004"
down_revision: str | Sequence[str] | None = "moderation_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "deals"
INDEX = "ix_deals_conversation_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "deals",
            ["conversation_id"],
            unique=False,
            schema=SCHEMA,
            postgresql_where=sa.text("conversation_id IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX,
            table_name="deals",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
