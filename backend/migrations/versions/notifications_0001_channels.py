"""notifications_0001: каналы доставки (ARCHITECTURE §7.3, §11.1, DEVELOPMENT_PLAN 1.4b).

`channels` — куда доставлять уведомления: личный чат с ботом (`telegram`, адрес — chat_id),
позже токены APNs/FCM и e-mail. Строка появляется, когда пользователь разрешил боту
писать (`/start` или `requestWriteAccess`); `disabled_at` — бот заблокирован (403, шаг 2.3).
Один адрес канала — одна строка (`uq_channels_kind_address`). `user_id` ссылается на
identity.users (identity ниже notifications по DAG, §5.2 п. 4): FK на чужую схему есть
только здесь, в моделях его нет (migrations/env.py). Таблица новая: FK проверяется мгновенно.

Ревизия: notifications_0001 (2026-09-27 13:35:53.466047+00:00)
Предыдущая: platform_0003

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

revision: str = 'notifications_0001'
down_revision: str | Sequence[str] | None = 'platform_0003'
branch_labels: str | Sequence[str] | None = ('notifications',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('channels',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('granted_via', sa.String(length=17), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("granted_via IN ('bot_start', 'mini_app')", name=op.f('ck_channels_granted_via')),
    sa.CheckConstraint("kind IN ('telegram', 'apns', 'fcm', 'email')", name=op.f('ck_channels_kind')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_channels_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channels')),
    sa.UniqueConstraint('kind', 'address', name=op.f('uq_channels_kind_address')),
    schema='notifications'
    )
    op.create_index('ix_channels_user_id', 'channels', ['user_id'], unique=False, schema='notifications')


def downgrade() -> None:
    op.drop_index('ix_channels_user_id', table_name='channels', schema='notifications')
    op.drop_table('channels', schema='notifications')
