"""platform_0005: сегмент «Вещи» на Главной в бете выключен (Q26, DEVELOPMENT_PLAN 7.5).

Флаг `goods.segment` заводила platform_0002 включённым — тогда S58 была лишь заглушкой. По
умолчанию Q26 («в бете выключено, включаем на запуске») сегмент и S58 с кнопкой «Сообщить о
запуске» видны только после включения флага в админке — без релиза. Миграция выключает флаг
один раз; дальше им управляет админка. Откат возвращает прежнее значение.

Ревизия: platform_0005 (2026-10-04 10:05:00.000000+00:00)
Предыдущая: notifications_0007

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0005"
down_revision: str | Sequence[str] | None = "notifications_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GOODS_SEGMENT = "goods.segment"


def _set(enabled: bool) -> None:
    op.execute(
        f"UPDATE platform.feature_flags SET enabled = {str(enabled).lower()}, updated_at = now()"
        f" WHERE key = '{GOODS_SEGMENT}'"
    )


def upgrade() -> None:
    _set(False)


def downgrade() -> None:
    _set(True)
