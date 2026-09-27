"""catalog_0001: категории, теги, словарь поиска (ARCHITECTURE §7.3, §7.5, §9, DEVELOPMENT_PLAN 1.3b).

Названия — JSONB с CHECK локалей (ru и sr-Cyrl обязательны). Дерево — `parent_id` и
денормализованный `path int[]` (предки и сам узел) под GIN: фильтр «с подкатегориями» —
`&&` без рекурсии. `path` и `depth` пишет триггер: при вставке и смене `parent_id` — от
родителя, при смене `path` — каскадом по потомкам; глубина ≤ 3 (CHECK). Словарь
`search_terms`: `norm` = platform.search_norm(term) — генерируемая колонка, один ключ для
ru, sr-Latn, sr-Cyrl и en; btree для префикса (коллация кластера — builtin C.UTF-8) и
GiST pg_trgm для опечаток. Данные — `cli seed`.

Ревизия: catalog_0001 (2026-09-27 11:59:55.194243+00:00)
Предыдущая: geo_0001

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


revision: str = 'catalog_0001'
down_revision: str | Sequence[str] | None = 'geo_0001'
branch_labels: str | Sequence[str] | None = ('catalog',)
depends_on: str | Sequence[str] | None = None

CATEGORY_PATH = r"""
-- path = path родителя || id, depth = cardinality(path). Корень — {id}.
CREATE FUNCTION catalog.set_category_path() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_id IS NULL THEN
    NEW.path := ARRAY[NEW.id];
  ELSE
    SELECT c.path || NEW.id INTO NEW.path FROM catalog.categories AS c WHERE c.id = NEW.parent_id;
  END IF;
  NEW.depth := cardinality(NEW.path);
  RETURN NEW;
END $$;

-- Сменился path — потомки пересчитывают свой от родителя. Цикл в дереве упирается в
-- CHECK глубины.
CREATE FUNCTION catalog.cascade_category_path() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE catalog.categories SET parent_id = parent_id WHERE parent_id = NEW.id;
  RETURN NULL;
END $$;

CREATE TRIGGER set_path BEFORE INSERT OR UPDATE OF parent_id, path ON catalog.categories
  FOR EACH ROW EXECUTE FUNCTION catalog.set_category_path();

CREATE TRIGGER cascade_path AFTER UPDATE ON catalog.categories
  FOR EACH ROW WHEN (OLD.path IS DISTINCT FROM NEW.path)
  EXECUTE FUNCTION catalog.cascade_category_path();
"""

DROP_CATEGORY_PATH = r"""
DROP TRIGGER IF EXISTS cascade_path ON catalog.categories;
DROP TRIGGER IF EXISTS set_path ON catalog.categories;
DROP FUNCTION IF EXISTS catalog.cascade_category_path(), catalog.set_category_path();
"""


def upgrade() -> None:
    op.create_table('categories',
    sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('path', sa.ARRAY(sa.Integer()), nullable=False),
    sa.Column('depth', sa.SmallInteger(), nullable=False),
    sa.Column('icon', sa.String(length=32), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('jobs_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('max_responses', sa.SmallInteger(), server_default=sa.text('5'), nullable=False),
    sa.Column('price_hint', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('risk_level', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('seed_hash', sa.String(length=64), nullable=True),
    sa.CheckConstraint("jsonb_typeof(name) = 'object' AND name <> '{}'::jsonb AND (name - ARRAY['ru', 'sr-Latn', 'sr-Cyrl', 'en']::text[]) = '{}'::jsonb", name=op.f('ck_categories_name_locales')),
    sa.CheckConstraint("jsonb_typeof(price_hint) = 'object'", name=op.f('ck_categories_price_hint_object')),
    sa.CheckConstraint("name ?& ARRAY['ru', 'sr-Cyrl']", name=op.f('ck_categories_name_required_locales')),
    sa.CheckConstraint('cardinality(path) = depth AND path[depth] = id', name=op.f('ck_categories_path')),
    sa.CheckConstraint('depth BETWEEN 1 AND 3', name=op.f('ck_categories_depth')),
    sa.CheckConstraint('max_responses > 0', name=op.f('ck_categories_max_responses')),
    sa.CheckConstraint('risk_level BETWEEN 0 AND 2', name=op.f('ck_categories_risk_level')),
    sa.ForeignKeyConstraint(['parent_id'], ['catalog.categories.id'], name=op.f('fk_categories_parent_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('slug', name=op.f('uq_categories_slug')),
    schema='catalog'
    )
    op.create_index('ix_categories_path', 'categories', ['path'], unique=False, schema='catalog', postgresql_using='gin')
    op.execute(CATEGORY_PATH)
    op.create_table('tags',
    sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(name) = 'object' AND name <> '{}'::jsonb AND (name - ARRAY['ru', 'sr-Latn', 'sr-Cyrl', 'en']::text[]) = '{}'::jsonb", name=op.f('ck_tags_name_locales')),
    sa.CheckConstraint("name ?& ARRAY['ru', 'sr-Cyrl']", name=op.f('ck_tags_name_required_locales')),
    sa.ForeignKeyConstraint(['category_id'], ['catalog.categories.id'], name=op.f('fk_tags_category_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tags')),
    sa.UniqueConstraint('slug', name=op.f('uq_tags_slug')),
    schema='catalog'
    )
    op.create_index('ix_tags_category_id', 'tags', ['category_id'], unique=False, schema='catalog')
    op.create_table('search_terms',
    sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
    sa.Column('term', sa.String(length=120), nullable=False),
    sa.Column('lang', sa.String(length=15), nullable=False),
    sa.Column('norm', sa.Text(), sa.Computed('platform.search_norm(term::text)', persisted=True), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=True),
    sa.Column('weight', sa.REAL(), server_default=sa.text('1.0'), nullable=False),
    sa.CheckConstraint("lang IN ('ru', 'sr-Latn', 'sr-Cyrl', 'en')", name=op.f('ck_search_terms_lang')),
    sa.ForeignKeyConstraint(['category_id'], ['catalog.categories.id'], name=op.f('fk_search_terms_category_id_categories')),
    sa.ForeignKeyConstraint(['tag_id'], ['catalog.tags.id'], name=op.f('fk_search_terms_tag_id_tags')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_search_terms')),
    schema='catalog'
    )
    op.create_index('ix_search_terms_norm', 'search_terms', ['norm'], unique=False, schema='catalog')
    op.create_index('ix_search_terms_norm_trgm', 'search_terms', ['norm'], unique=False, schema='catalog', postgresql_using='gist', postgresql_ops={'norm': 'gist_trgm_ops'})
    op.create_index('ix_search_terms_tag_id', 'search_terms', ['tag_id'], unique=False, schema='catalog')
    op.create_index('uq_search_terms_category_id_tag_id_lang_term', 'search_terms', ['category_id', 'tag_id', 'lang', 'term'], unique=True, schema='catalog', postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    op.drop_index('uq_search_terms_category_id_tag_id_lang_term', table_name='search_terms', schema='catalog', postgresql_nulls_not_distinct=True)
    op.drop_index('ix_search_terms_tag_id', table_name='search_terms', schema='catalog')
    op.drop_index('ix_search_terms_norm_trgm', table_name='search_terms', schema='catalog', postgresql_using='gist', postgresql_ops={'norm': 'gist_trgm_ops'})
    op.drop_index('ix_search_terms_norm', table_name='search_terms', schema='catalog')
    op.drop_table('search_terms', schema='catalog')
    op.drop_index('ix_tags_category_id', table_name='tags', schema='catalog')
    op.drop_table('tags', schema='catalog')
    op.execute(DROP_CATEGORY_PATH)
    op.drop_index('ix_categories_path', table_name='categories', schema='catalog', postgresql_using='gin')
    op.drop_table('categories', schema='catalog')
