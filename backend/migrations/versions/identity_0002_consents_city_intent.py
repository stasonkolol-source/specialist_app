"""identity_0002: журнал согласий, город и намерение пользователя.

Шаг 1.4a (ARCHITECTURE §7.3, §13.4, ADR-0018). `consents` — журнал акцептов: документ,
версия, время, платформа и адрес; одна действующая запись на документ и версию (повтор
галочки идемпотентен), отзыв — `withdrawn_at`. `users.home_city_id` ссылается на
geo.cities (справочник — лист DAG, §5.2 п. 4): FK на чужую схему есть только здесь, в
моделях его нет (migrations/env.py). Колонки новые и пустые: FK проверяется мгновенно.

Ревизия: identity_0002 (2026-09-27 12:22:48.589372+00:00)
Предыдущая: catalog_0001

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

revision: str = 'identity_0002'
down_revision: str | Sequence[str] | None = 'catalog_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('consents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('document', sa.String(length=29), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=15), nullable=False),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.CheckConstraint("document IN ('terms', 'privacy', 'age_18', 'performer_declaration', 'analytics', 'marketing', 'precise_location', 'ai_processing')", name=op.f('ck_consents_document')),
    sa.CheckConstraint("source IN ('tma', 'ios', 'android', 'web', 'admin')", name=op.f('ck_consents_source')),
    sa.ForeignKeyConstraint(['user_id'], ['identity.users.id'], name=op.f('fk_consents_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consents')),
    schema='identity'
    )
    op.create_index('uq_consents_user_id_document_version', 'consents', ['user_id', 'document', 'version'], unique=True, schema='identity', postgresql_where=sa.text('withdrawn_at IS NULL'))
    op.add_column('users', sa.Column('home_city_id', sa.Integer(), nullable=True), schema='identity')
    op.create_foreign_key(op.f('fk_users_home_city_id_cities'), 'users', 'cities', ['home_city_id'], ['id'], source_schema='identity', referent_schema='geo')
    op.add_column('users', sa.Column('intent', sa.String(length=14), nullable=True), schema='identity')
    op.create_check_constraint(op.f('ck_users_intent'), 'users', "intent IN ('client', 'pro', 'casual')", schema='identity')


def downgrade() -> None:
    op.drop_constraint(op.f('ck_users_intent'), 'users', schema='identity', type_='check')
    op.drop_column('users', 'intent', schema='identity')
    op.drop_constraint(op.f('fk_users_home_city_id_cities'), 'users', schema='identity', type_='foreignkey')
    op.drop_column('users', 'home_city_id', schema='identity')
    op.drop_index('uq_consents_user_id_document_version', table_name='consents', schema='identity', postgresql_where=sa.text('withdrawn_at IS NULL'))
    op.drop_table('consents', schema='identity')
