"""notifications_0002: центр уведомлений, доставки, настройки (ARCHITECTURE §7.3, §11.2, 2.3a).

- `notifications` — центр уведомлений (S42) и источник доставок: `dedupe_key` UNIQUE делает
  повтор события безвредным; `payload` — машинные параметры шаблона, текст собирается при
  показе на языке читателя; `in_app` — виден ли в центре (канал включён для группы).
- `deliveries` — отправка в канал не раньше `not_before` (тихие часы); одна на пару
  уведомление × канал (`uq_deliveries_notification_id_channel_id`).
- `preferences` — выбор «группа × канал» только там, где человек что-то менял;
  `user_settings` — тихие часы (по Europe/Belgrade) и час дайджеста; строки нет — умолчания.

`user_id` ссылается на identity.users (identity ниже notifications по DAG): FK на чужую
схему — только здесь, в моделях его нет (migrations/env.py). Таблицы новые: FK и индексы
создаются мгновенно.

Ревизия: notifications_0002 (2026-09-30 07:57:57.340092+00:00)
Предыдущая: media_0003

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

revision: str = 'notifications_0002'
down_revision: str | Sequence[str] | None = 'media_0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = (
    "'job.matched', 'response.received', 'response.accepted', 'response.not_selected',"
    " 'job.invited', 'message.received', 'deal.proposed', 'deal.cancelled', 'dispute.opened',"
    " 'deal.reminder', 'deal.completion_prompt', 'review.request', 'review.published',"
    " 'moderation.decision', 'job.expiring', 'job.expired', 'profile.stale_reminder',"
    " 'account.restricted'"
)
GROUPS = "'job_matches', 'responses', 'messages', 'deals', 'marketing', 'account'"


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('dedupe_key', sa.String(length=255), nullable=False),
    sa.Column('priority', sa.SmallInteger(), nullable=False),
    sa.Column('in_app', sa.Boolean(), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint(f"type IN ({TYPES})", name=op.f('ck_notifications_type')),
    sa.CheckConstraint('priority BETWEEN 0 AND 3', name=op.f('ck_notifications_priority')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_notifications_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    sa.UniqueConstraint('dedupe_key', name=op.f('uq_notifications_dedupe_key')),
    schema='notifications'
    )
    op.create_index('ix_notifications_unread', 'notifications', ['user_id'], unique=False, schema='notifications', postgresql_where=sa.text('in_app AND read_at IS NULL'))
    op.create_index('ix_notifications_user_id_id', 'notifications', ['user_id', 'id'], unique=False, schema='notifications', postgresql_where=sa.text('in_app'))
    op.create_table('preferences',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('event_group', sa.String(length=19), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('telegram', 'in_app')", name=op.f('ck_preferences_channel')),
    sa.CheckConstraint(f"event_group IN ({GROUPS})", name=op.f('ck_preferences_event_group')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_preferences_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'event_group', 'channel', name=op.f('pk_preferences')),
    schema='notifications'
    )
    op.create_table('user_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('quiet_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('quiet_start', sa.Time(), server_default=sa.text("'22:00:00'"), nullable=False),
    sa.Column('quiet_end', sa.Time(), server_default=sa.text("'08:00:00'"), nullable=False),
    sa.Column('digest_hour', sa.SmallInteger(), server_default=sa.text('9'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('digest_hour BETWEEN 0 AND 23', name=op.f('ck_user_settings_digest_hour')),
    sa.CheckConstraint('quiet_start <> quiet_end', name=op.f('ck_user_settings_quiet_window')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_user_settings_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings')),
    schema='notifications'
    )
    op.create_table('deliveries',
    sa.Column('notification_id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=18), nullable=False),
    sa.Column('attempts', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('provider_message_id', sa.String(length=64), nullable=True),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'sent', 'failed', 'suppressed')", name=op.f('ck_deliveries_status')),
    sa.ForeignKeyConstraint(['channel_id'], ['notifications.channels.id'], name=op.f('fk_deliveries_channel_id_channels')),
    sa.ForeignKeyConstraint(['notification_id'], ['notifications.notifications.id'], name=op.f('fk_deliveries_notification_id_notifications')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_deliveries')),
    sa.UniqueConstraint('notification_id', 'channel_id', name=op.f('uq_deliveries_notification_id_channel_id')),
    schema='notifications'
    )
    op.create_index('ix_deliveries_not_before', 'deliveries', ['not_before'], unique=False, schema='notifications', postgresql_where=sa.text("status = 'queued'"))


def downgrade() -> None:
    op.drop_index('ix_deliveries_not_before', table_name='deliveries', schema='notifications', postgresql_where=sa.text("status = 'queued'"))
    op.drop_table('deliveries', schema='notifications')
    op.drop_table('user_settings', schema='notifications')
    op.drop_table('preferences', schema='notifications')
    op.drop_index('ix_notifications_user_id_id', table_name='notifications', schema='notifications', postgresql_where=sa.text('in_app'))
    op.drop_index('ix_notifications_unread', table_name='notifications', schema='notifications', postgresql_where=sa.text('in_app AND read_at IS NULL'))
    op.drop_table('notifications', schema='notifications')
