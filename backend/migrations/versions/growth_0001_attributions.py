"""growth_0001: атрибуция первого касания (ARCHITECTURE §7.3, §11.4, DEVELOPMENT_PLAN 1.4b).

`attributions` — откуда пришёл пользователь: тип ссылки (`source`), сырой код `startapp`
или `/start` (`start_param`, только в синтаксисе Telegram), суффикс `_r` (`referral_code`)
и где вошёл (`entry_point`). Одна строка на пользователя: первичный ключ `user_id` держит
правило «второе касание не перезаписывает». FK на identity.users (identity ниже growth по
DAG, §5.2 п. 4) — только здесь, в моделях его нет (migrations/env.py).

Ревизия: growth_0001 (2026-09-27 13:35:53.466047+00:00)
Предыдущая: notifications_0001

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

revision: str = 'growth_0001'
down_revision: str | Sequence[str] | None = 'notifications_0001'
branch_labels: str | Sequence[str] | None = ('growth',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('attributions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=18), nullable=False),
    sa.Column('start_param', sa.String(length=64), nullable=True),
    sa.Column('referral_code', sa.String(length=64), nullable=True),
    sa.Column('entry_point', sa.String(length=16), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("entry_point IN ('mini_app', 'bot')", name=op.f('ck_attributions_entry_point')),
    sa.CheckConstraint("source IN ('organic', 'job', 'specialist', 'chat', 'deal', 'home', 'goods', 'unknown')", name=op.f('ck_attributions_source')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_attributions_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_attributions')),
    schema='growth'
    )


def downgrade() -> None:
    op.drop_table('attributions', schema='growth')
