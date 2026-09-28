"""growth_0002: источник атрибуции `legal` — ссылки `l_terms`, `l_privacy`.

Шаг 1.6. Бот отвечает на `/terms` и `/privacy` кнопкой в S48 с кодом `l_<документ>`, и такую
ссылку можно переслать в чат: человек, который пришёл по ней, получает источник `legal`.
Новый CHECK — надмножество старого. DROP и ADD … NOT VALID берут ACCESS EXCLUSIVE, но без
проверки строк и коротко; транзакция миграции коммитится (autocommit_block), и VALIDATE
проверяет строки под SHARE UPDATE EXCLUSIVE — чтение и запись в это время идут. Так же
надо менять CHECK на больших таблицах. Откат возвращает старый список; строки с `legal`
откат не удаляет — VALIDATE тогда упадёт (ADR-0005: данные не теряем).

Ревизия: growth_0002 (2026-09-28 16:30:00.000000+00:00)
Предыдущая: platform_0004

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "growth_0002"
down_revision: str | Sequence[str] | None = "platform_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "growth.attributions"
CHECK = "ck_attributions_source"
OLD = "'organic', 'job', 'specialist', 'chat', 'deal', 'home', 'goods', 'unknown'"
NEW = "'organic', 'job', 'specialist', 'chat', 'deal', 'home', 'legal', 'goods', 'unknown'"


def _replace(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (source IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    _replace(OLD)
