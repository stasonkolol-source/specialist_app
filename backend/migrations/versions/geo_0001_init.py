"""geo_0001: города и районы (ARCHITECTURE §7.3, §7.6, DEVELOPMENT_PLAN 1.3a).

Названия — JSONB с CHECK локалей (ru и sr-Cyrl обязательны), точки — geography(Point, 4326),
границы — geometry(MultiPolygon, 4326) под явными GiST (спайк 0.6). Данные — `cli seed`.

Ревизия: geo_0001 (2026-09-27 11:27:46.706890+00:00)
Предыдущая: platform_0002

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'geo_0001'
down_revision: str | Sequence[str] | None = 'platform_0002'
branch_labels: str | Sequence[str] | None = ('geo',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('cities',
    sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('center', geoalchemy2.Geography(geometry_type='POINT', srid=4326, spatial_index=False), nullable=False),
    sa.Column('boundary', geoalchemy2.Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=False), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('seed_hash', sa.String(length=64), nullable=True),
    sa.CheckConstraint("jsonb_typeof(name) = 'object' AND name <> '{}'::jsonb AND (name - ARRAY['ru', 'sr-Latn', 'sr-Cyrl', 'en']::text[]) = '{}'::jsonb", name=op.f('ck_cities_name_locales')),
    sa.CheckConstraint("name ?& ARRAY['ru', 'sr-Cyrl']", name=op.f('ck_cities_name_required_locales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cities')),
    sa.UniqueConstraint('slug', name=op.f('uq_cities_slug')),
    schema='geo'
    )
    op.create_index('ix_cities_boundary', 'cities', ['boundary'], unique=False, schema='geo', postgresql_using='gist')
    op.create_table('districts',
    sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
    sa.Column('city_id', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('aliases', sa.ARRAY(sa.String(length=64)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('center', geoalchemy2.Geography(geometry_type='POINT', srid=4326, spatial_index=False), nullable=False),
    sa.Column('boundary', geoalchemy2.Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=False), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('seed_hash', sa.String(length=64), nullable=True),
    sa.CheckConstraint("jsonb_typeof(name) = 'object' AND name <> '{}'::jsonb AND (name - ARRAY['ru', 'sr-Latn', 'sr-Cyrl', 'en']::text[]) = '{}'::jsonb", name=op.f('ck_districts_name_locales')),
    sa.CheckConstraint("kind IN ('municipality', 'neighborhood')", name=op.f('ck_districts_kind')),
    sa.CheckConstraint("name ?& ARRAY['ru', 'sr-Cyrl']", name=op.f('ck_districts_name_required_locales')),
    sa.ForeignKeyConstraint(['city_id'], ['geo.cities.id'], name=op.f('fk_districts_city_id_cities')),
    sa.ForeignKeyConstraint(['parent_id'], ['geo.districts.id'], name=op.f('fk_districts_parent_id_districts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_districts')),
    schema='geo'
    )
    op.create_index('ix_districts_boundary', 'districts', ['boundary'], unique=False, schema='geo', postgresql_using='gist')
    op.create_index('ix_districts_center', 'districts', ['center'], unique=False, schema='geo', postgresql_using='gist')
    op.create_index('uq_districts_city_id_slug', 'districts', ['city_id', 'slug'], unique=True, schema='geo')


def downgrade() -> None:
    op.drop_index('uq_districts_city_id_slug', table_name='districts', schema='geo')
    op.drop_index('ix_districts_center', table_name='districts', schema='geo', postgresql_using='gist')
    op.drop_index('ix_districts_boundary', table_name='districts', schema='geo', postgresql_using='gist')
    op.drop_table('districts', schema='geo')
    op.drop_index('ix_cities_boundary', table_name='cities', schema='geo', postgresql_using='gist')
    op.drop_table('cities', schema='geo')
