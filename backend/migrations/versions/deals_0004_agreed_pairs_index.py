"""deals_0004: договаривалась ли пара — по индексу (контакты пары открыты, ADR-0010, 2026-10-04).

Переписка спрашивает, договаривались ли клиент и исполнитель диалога хоть раз — в любом диалоге
и в любой роли: сделка этой пары с `agreed_at` (ставится при `agreed` и не стирается). Индекс
(client_id, performer_id) частичный — только договорённые сделки; предложения, которые
отклонили или которые истекли, в него не попадают. Индекс — CONCURRENTLY.

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
INDEX = "ix_deals_ever_agreed_client_id_performer_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "deals",
            ["client_id", "performer_id"],
            unique=False,
            schema=SCHEMA,
            postgresql_where=sa.text("agreed_at IS NOT NULL"),
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
