"""media_0004: legal hold удалённых файлов (ADR-0016 §6, DEVELOPMENT_PLAN 2.5a).

`assets.held_until` — файл удалённого пользователем контента — доказательство открытого
кейса модерации (2.5a) или спора (6.1c): `media.purge_deleted` не стирает его объекты, а
откладывает проверку до `held_until`. Колонка nullable, без значения: добавление не
переписывает таблицу.

Ревизия: media_0004 (2026-09-30 21:05:00.000000+00:00)
Предыдущая: identity_0003

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

revision: str = "media_0004"
down_revision: str | Sequence[str] | None = "identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        schema="media",
    )


def downgrade() -> None:
    op.drop_column("assets", "held_until", schema="media")
