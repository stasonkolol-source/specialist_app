"""identity_0001: пользователи, способы входа, сессии, санкции, роли персонала.

Шаг 0.15a (ARCHITECTURE §7.3, ADR-0009). `home_city_id` с FK на geo.cities добавит
identity_0002 (шаг 1.4a). Сессии хранят хэш текущего и предыдущего refresh и время
ротации — детектор кражи из docs/spikes/0.14-initdata-jwt.md п. 7.

Ревизия: identity_0001 (2026-09-27 10:00:58.394990+00:00)
Предыдущая: platform_0001

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

revision: str = 'identity_0001'
down_revision: str | Sequence[str] | None = 'platform_0001'
branch_labels: str | Sequence[str] | None = ('identity',)
depends_on: str | Sequence[str] | None = 'platform_0001'


def upgrade() -> None:
    op.create_table('users',
    sa.Column('status', sa.String(length=15), server_default='active', nullable=False),
    sa.Column('display_name', sa.String(length=64), nullable=False),
    sa.Column('avatar_media_id', sa.Uuid(), nullable=True),
    sa.Column('ui_locale', sa.String(length=15), server_default='ru', nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='Europe/Belgrade', nullable=False),
    sa.Column('phone_e164', sa.String(length=16), nullable=True),
    sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('identity_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trust_level', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('privacy', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("status IN ('active', 'deleted')", name=op.f('ck_users_status')),
    sa.CheckConstraint("ui_locale IN ('ru', 'sr-Latn', 'sr-Cyrl', 'en')", name=op.f('ck_users_ui_locale')),
    sa.CheckConstraint('trust_level BETWEEN 0 AND 3', name=op.f('ck_users_trust_level_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    schema='identity'
    )
    op.create_index('uq_users_phone_e164', 'users', ['phone_e164'], unique=True, schema='identity', postgresql_where=sa.text('phone_e164 IS NOT NULL AND deleted_at IS NULL'))
    op.create_table('auth_identities',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('profile', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint("provider IN ('telegram', 'apple', 'google', 'phone', 'email')", name=op.f('ck_auth_identities_provider')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_auth_identities_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_identities')),
    sa.UniqueConstraint('provider', 'subject', name=op.f('uq_auth_identities_provider_subject')),
    schema='identity'
    )
    op.create_index(op.f('ix_auth_identities_user_id'), 'auth_identities', ['user_id'], unique=False, schema='identity')
    op.create_table('restrictions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=26), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=18), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lifted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint("kind IN ('posting_blocked', 'responding_blocked', 'messaging_blocked', 'shadow_banned', 'suspended', 'banned')", name=op.f('ck_restrictions_kind')),
    sa.CheckConstraint("source IN ('moderation', 'system')", name=op.f('ck_restrictions_source')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_restrictions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_restrictions')),
    schema='identity'
    )
    op.create_index('ix_restrictions_user_id_in_force', 'restrictions', ['user_id'], unique=False, schema='identity', postgresql_where=sa.text('lifted_at IS NULL'))
    op.create_table('sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.String(length=15), nullable=False),
    sa.Column('bot_id', sa.BigInteger(), nullable=True),
    sa.Column('amr', sa.ARRAY(sa.String(length=32)), nullable=False),
    sa.Column('refresh_token_hash', sa.LargeBinary(length=32), nullable=False),
    sa.Column('previous_refresh_hash', sa.LargeBinary(length=32), nullable=True),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoke_reason', sa.String(length=23), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint("platform IN ('tma', 'ios', 'android', 'web', 'admin')", name=op.f('ck_sessions_platform')),
    sa.CheckConstraint("revoke_reason IN ('logout', 'refresh_reused', 'restricted', 'account_deleted')", name=op.f('ck_sessions_revoke_reason')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('refresh_token_hash', name=op.f('uq_sessions_refresh_token_hash')),
    schema='identity'
    )
    op.create_index('ix_sessions_user_id_active', 'sessions', ['user_id'], unique=False, schema='identity', postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('status_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.String(length=32), nullable=False),
    sa.Column('to_status', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_status_history_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_status_history')),
    schema='identity'
    )
    op.create_index(op.f('ix_status_history_user_id'), 'status_history', ['user_id'], unique=False, schema='identity')
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=17), nullable=False),
    sa.Column('granted_by', sa.Uuid(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'moderator', 'support')", name=op.f('ck_user_roles_role')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_user_roles_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'role', name=op.f('pk_user_roles')),
    schema='identity'
    )


def downgrade() -> None:
    op.drop_table('user_roles', schema='identity')
    op.drop_index(op.f('ix_status_history_user_id'), table_name='status_history', schema='identity')
    op.drop_table('status_history', schema='identity')
    op.drop_index('ix_sessions_user_id_active', table_name='sessions', schema='identity', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_table('sessions', schema='identity')
    op.drop_index('ix_restrictions_user_id_in_force', table_name='restrictions', schema='identity', postgresql_where=sa.text('lifted_at IS NULL'))
    op.drop_table('restrictions', schema='identity')
    op.drop_index(op.f('ix_auth_identities_user_id'), table_name='auth_identities', schema='identity')
    op.drop_table('auth_identities', schema='identity')
    op.drop_index('uq_users_phone_e164', table_name='users', schema='identity', postgresql_where=sa.text('phone_e164 IS NOT NULL AND deleted_at IS NULL'))
    op.drop_table('users', schema='identity')
