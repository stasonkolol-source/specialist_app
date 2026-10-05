"""platform_0007: утверждённая редакция «1» правил и политики вместо черновиков draft-1.

K22: владелец утвердил черновики правил площадки, политики конфиденциальности и политики
модерации как есть (2026-10-05). Тексты — backend/content/legal/<документ>/1; папки draft-1
остаются: по ним видно, с какой редакцией соглашались раньше. Миграция переключает
`legal_versions` client-config на «1» только там, где ещё стоит draft-1 из platform_0003:
версию, выбранную в админке, не трогает. С новой версией создающие действия снова требуют
галочки S02c — identity сверяет согласие с `legal_versions`. Политики модерации в
`legal_versions` нет: действует последняя опубликованная редакция (moderation/application/
policy.py), «1» — с выкладки. Откат возвращает draft-1 только там, где стоит «1».

Ревизия: platform_0007 (2026-10-05 15:30:00.000000+00:00)
Предыдущая: deals_0004

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0007"
down_revision: str | Sequence[str] | None = "deals_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DRAFT = "draft-1"
APPROVED = {"terms": "1", "privacy": "1"}
"""Документ → утверждённая версия (папка backend/content/legal/<документ>/1)."""


def _switch(document: str, old: str, new: str) -> None:
    # updated_by = NULL: значение задала миграция, а не сотрудник (platform_0006)
    op.execute(
        f"""
        UPDATE platform.client_config
        SET value = value || jsonb_build_object('{document}', '{new}'),
            updated_at = now(), updated_by = NULL
        WHERE key = 'legal_versions' AND value->>'{document}' = '{old}'
        """
    )


def upgrade() -> None:
    for document, version in APPROVED.items():
        _switch(document, DRAFT, version)


def downgrade() -> None:
    for document, version in APPROVED.items():
        _switch(document, version, DRAFT)
