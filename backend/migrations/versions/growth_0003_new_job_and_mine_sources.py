"""growth_0003: источники атрибуции `new_job` и `mine` — ссылки `n` и `m_jobs`.

Шаг 5.6. Бот отвечает на `/new` кнопкой мастера новой заявки (код `n`), на `/jobs` — кнопками
своих заявок и «Мои заявки» (код `m_jobs`). Ссылку `n` пересылают в чаты: человек, который
пришёл по ней, получает источник `new_job`. CHECK меняется так же, как в growth_0002: новый —
надмножество старого, NOT VALID и VALIDATE вне транзакции миграции. Откат возвращает старый
список; строки с новыми источниками откат не удаляет — VALIDATE тогда упадёт (ADR-0005:
данные не теряем).

Ревизия: growth_0003 (2026-10-02 18:30:00.000000+00:00)
Предыдущая: jobs_0008

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "growth_0003"
down_revision: str | Sequence[str] | None = "jobs_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "growth.attributions"
CHECK = "ck_attributions_source"
OLD = "'organic', 'job', 'specialist', 'chat', 'deal', 'home', 'legal', 'goods', 'unknown'"
NEW = (
    "'organic', 'job', 'specialist', 'chat', 'deal', 'home', 'new_job', 'mine', 'legal',"
    " 'goods', 'unknown'"
)


def _replace(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (source IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    _replace(OLD)
