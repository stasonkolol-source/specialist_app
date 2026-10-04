"""media_0006: pHash фото портфолио — поиск дубликатов у других аккаунтов (DEVELOPMENT_PLAN 7.6).

`assets.phash bit(64)` — тип из ARCHITECTURE §5.8 (там же колонка нужна объявлениям «Вещей»):
64 бита DCT-хэша фото портфолио или постера ролика, расстояние — `bit_count(a # b)`. Колонка
nullable, без значения: добавление не переписывает таблицу. Индекса нет: на объёмах MVP
(десятки тысяч фото портфолио) поиск — полный проход по готовым файлам портфолио за
миллисекунды; индекс по частям хэша (multi-index hashing) — когда фото станет на порядки
больше. Уже обработанные фото хэша не получают — сравниваются только новые загрузки.

Ревизия: media_0006 (2026-10-04 14:05:00.000000+00:00)
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
from sqlalchemy.dialects import postgresql

revision: str = "media_0006"
down_revision: str | Sequence[str] | None = "platform_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("phash", postgresql.BIT(64), nullable=True),
        schema="media",
    )


def downgrade() -> None:
    op.drop_column("assets", "phash", schema="media")
