"""moderation_0010: версия содержимого кейса и сообщение его карточки (QA ADV-11).

Модератор одобрял версию, которой не видел: автор правил заявку или профиль после карточки, и
«Одобрить» публиковало правку. Кейс помнит версию, которую показывает карточка
(`entity_version` — редакция объекта: jobs_0011, specialists_0004, `jobs.responses.revision`),
одобрение публикует только её, а правка закрывает кейс как устаревший (`superseded`) и открывает
новый с новой карточкой. `card_message_id` — сообщение карточки в чате модераторов: у
устаревшего кейса бот гасит кнопки. Обе колонки nullable — без переписывания таблицы; прежние
кейсы версию не помнят и решаются как раньше.

Ревизия: moderation_0010 (2026-10-05 20:32:00.000000+00:00)
Предыдущая: specialists_0004

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

revision: str = "moderation_0010"
down_revision: str | Sequence[str] | None = "specialists_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"


def upgrade() -> None:
    op.add_column("cases", sa.Column("entity_version", sa.Integer(), nullable=True), schema=SCHEMA)
    op.add_column(
        "cases", sa.Column("card_message_id", sa.BigInteger(), nullable=True), schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_column("cases", "card_message_id", schema=SCHEMA)
    op.drop_column("cases", "entity_version", schema=SCHEMA)
