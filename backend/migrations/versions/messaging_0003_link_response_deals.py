"""messaging_0003: диалогам по отклику — сделку этого отклика (UXM-14).

Диалог по отклику, начатый уже после выбора исполнителя («Поделиться контактом» или «Написать»
на S26), создавался без `deal_id`: шапка S30 и список S29 писали «Сделки пока нет» рядом с «Вы
уже договаривались — контакты открыты». Новые диалоги теперь берут сделку отклика при создании
(start_conversation); миграция связывает уже созданные. У отклика не больше одной сделки
(`uq_deals_response_id`). Откат не нужен: отвязать сделку значило бы вернуть ошибку — downgrade
ничего не делает.

Ревизия: messaging_0003 (2026-10-05 21:30:00.000000+00:00)
Предыдущая: reviews_0005

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "messaging_0003"
down_revision: str | Sequence[str] | None = "reviews_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # диалогов по отклику без сделки — единицы (MVP): одним UPDATE, без батчей
    op.execute(
        """
        UPDATE messaging.conversations AS c
           SET deal_id = d.id
          FROM deals.deals AS d
         WHERE c.deal_id IS NULL
           AND c.response_id IS NOT NULL
           AND d.response_id = c.response_id
        """
    )


def downgrade() -> None:
    pass
