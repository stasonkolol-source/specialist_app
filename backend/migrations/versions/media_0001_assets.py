"""media_0001: медиафайлы (ARCHITECTURE §7.3 «media: assets», §7.8, §10, DEVELOPMENT_PLAN 2.1).

`assets` — файл со своим жизненным циклом `pending_upload → uploaded → processing → ready /
failed / rejected` (и `deleted`): клиент грузит его прямо в хранилище по presigned-ссылке,
`complete` сверяет HEAD. `upload_id` — id multipart-загрузки (видео больше 50 MB),
`failure_reason` — почему `failed`, `etag` — ETag оригинала, сверенного при complete. Поля обработки (варианты, размеры, sha256, placeholder,
модерация) заполняет шаг 2.2. FK на identity.users (identity ниже media по DAG) — только
здесь, в моделях его нет (migrations/env.py).

Ревизия: media_0001 (2026-09-29 16:23:33.200797+00:00)
Предыдущая: growth_0002

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

revision: str = 'media_0001'
down_revision: str | Sequence[str] | None = 'growth_0002'
branch_labels: str | Sequence[str] | None = ('media',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('assets',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=22), server_default='pending_upload', nullable=False),
    sa.Column('bucket', sa.String(length=32), nullable=False),
    sa.Column('object_key', sa.String(length=255), nullable=False),
    sa.Column('upload_id', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('etag', sa.Text(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('sha256', sa.LargeBinary(length=32), nullable=True),
    sa.Column('variants', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('placeholder', sa.Text(), nullable=True),
    sa.Column('moderation_status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('moderation_labels', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('failure_reason', sa.String(length=17), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint("failure_reason IN ('abandoned', 'mismatch')", name=op.f('ck_assets_failure_reason')),
    sa.CheckConstraint("kind IN ('image', 'video', 'document')", name=op.f('ck_assets_kind')),
    sa.CheckConstraint("moderation_status IN ('pending', 'approved', 'flagged', 'rejected')", name=op.f('ck_assets_moderation_status')),
    sa.CheckConstraint("purpose IN ('avatar', 'portfolio', 'job', 'message', 'review', 'verification')", name=op.f('ck_assets_purpose')),
    sa.CheckConstraint("status IN ('pending_upload', 'uploaded', 'processing', 'ready', 'failed', 'rejected', 'deleted')", name=op.f('ck_assets_status')),
    sa.ForeignKeyConstraint(['owner_id'], ['identity.users.id'], name=op.f('fk_assets_owner_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assets')),
    schema='media'
    )
    op.create_index('ix_assets_owner_id_created_at', 'assets', ['owner_id', sa.literal_column('created_at DESC')], unique=False, schema='media')
    op.create_index('ix_assets_status_created_at', 'assets', ['status', 'created_at'], unique=False, schema='media', postgresql_where=sa.text("status IN ('pending_upload', 'uploaded', 'processing')"))


def downgrade() -> None:
    op.drop_index('ix_assets_status_created_at', table_name='assets', schema='media', postgresql_where=sa.text("status IN ('pending_upload', 'uploaded', 'processing')"))
    op.drop_index('ix_assets_owner_id_created_at', table_name='assets', schema='media')
    op.drop_table('assets', schema='media')
