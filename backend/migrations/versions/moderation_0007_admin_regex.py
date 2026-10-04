"""moderation_0007: регулярки контент-правил заводит и админка (DEVELOPMENT_PLAN 2.7b).

`ck_content_rules_regex_from_seed` (moderation_0001) пускал регулярки только из сида: стандартный
`re` перебирает варианты неудачного шаблона экспоненциально. Теперь регулярки ищет RE2
(modules/moderation/domain/rules.py) — время линейно при любом шаблоне, а правку из админки
проверяет то же, что сид в `cli seeds-validate`. CHECK снимается; таблица — сотни строк,
блокировка короткая. Откат возвращает CHECK; если в админке уже завели регулярки, он не
создастся (ADR-0005: данные не теряем) — такие строки сначала разбирают руками.

Ревизия: moderation_0007 (2026-10-04 18:00:00.000000+00:00)
Предыдущая: notifications_0008

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "moderation_0007"
down_revision: str | Sequence[str] | None = "notifications_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
CHECK = "ck_content_rules_regex_from_seed"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "content_rules", type_="check", schema=SCHEMA)


def downgrade() -> None:
    op.create_check_constraint(
        op.f(CHECK), "content_rules", "kind <> 'regex' OR origin = 'seed'", schema=SCHEMA
    )
