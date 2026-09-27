"""platform_0002: идемпотентность, аудит, конфигурация клиентов, feature flags.

Шаг 1.1 (ADR-0020 §4, ARCHITECTURE §7.3, §7.10). Журнал аудита — только добавление: у
роли app отозваны UPDATE и DELETE, UPDATE запрещён триггером для всех ролей (удаление по
ретеншну — отдельной ролью обслуживания, шаг 6.x). Начальные данные: пустые min_versions
и legal_versions, публичный флаг goods.segment (значок «Вещи» и тизер S58, ADR-0019).

Ревизия: platform_0002 (2026-09-27 10:57:52.640683+00:00)
Предыдущая: identity_0001

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

revision: str = 'platform_0002'
down_revision: str | Sequence[str] | None = 'identity_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY = """
REVOKE UPDATE, DELETE, TRUNCATE ON platform.audit_log FROM app;
CREATE FUNCTION platform.audit_log_append_only() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'platform.audit_log is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON platform.audit_log
  FOR EACH ROW EXECUTE FUNCTION platform.audit_log_append_only();
"""

SEED = """
INSERT INTO platform.client_config (key, value) VALUES
  ('min_versions', '{}'::jsonb),
  ('legal_versions', '{}'::jsonb);
INSERT INTO platform.feature_flags (key, enabled, public, description) VALUES
  ('goods.segment', true, true, 'Сегмент «Вещи» на главной с бейджем «скоро» (ADR-0019)');
"""


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('actor_kind', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=128), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log')),
    schema='platform'
    )
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id', sa.literal_column('created_at DESC')], unique=False, schema='platform')
    op.create_table('client_config',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_client_config')),
    schema='platform'
    )
    op.create_table('feature_flags',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('public', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_feature_flags')),
    schema='platform'
    )
    op.create_table('idempotency_keys',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('request_hash', sa.LargeBinary(length=32), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('user_id', 'key', name=op.f('pk_idempotency_keys')),
    schema='platform'
    )
    op.create_index('ix_idempotency_keys_created_at', 'idempotency_keys', ['created_at'], unique=False, schema='platform')
    op.execute(APPEND_ONLY)
    op.execute(SEED)


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.audit_log_append_only() CASCADE")
    op.drop_index('ix_idempotency_keys_created_at', table_name='idempotency_keys', schema='platform')
    op.drop_table('idempotency_keys', schema='platform')
    op.drop_table('feature_flags', schema='platform')
    op.drop_table('client_config', schema='platform')
    op.drop_index('ix_audit_log_entity', table_name='audit_log', schema='platform')
    op.drop_table('audit_log', schema='platform')
