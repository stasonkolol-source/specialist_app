"""platform_0001: схемы модулей, поиск ru/sr, коллации, схема Procrastinate.

Ревизия: platform_0001 (2026-09-27)
Предыдущая: —

Всё создаёт роль migrator без суперпользователя (DEVELOPMENT_PLAN 0.9):
- схемы модулей MVP (ARCHITECTURE §7.1);
- функции поиска и конфигурации FTS из лаборатории (research/07, lab/sql/02, 03) — в схеме
  platform, со схемой в каждой ссылке: работают в генерируемых колонках и после pg_restore;
- ICU-коллации ru / sr-Latn / sr-Cyrl (lab/sql/06);
- схема procrastinate с SQL Procrastinate 3.10 (docs/spikes/0.8). Обновление Procrastinate —
  отдельной миграцией с его SQL-миграциями.

Служебные таблицы platform (идемпотентность, аудит, client-config, флаги) — platform_0002.
"""

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

from app.platform.db.registry import MODULE_SCHEMAS

revision: str = "platform_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("platform",)
depends_on: str | Sequence[str] | None = None

SEARCH_FUNCTIONS = r"""
-- Неизменяемая обёртка над unaccent (сама unaccent() — STABLE и не годится для индексов).
CREATE FUNCTION platform.f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN public.unaccent('public.unaccent'::regdictionary, $1);

-- Сербская кириллица → латиница (гаевица), 1:1 включая љ њ џ.
CREATE FUNCTION platform.sr_cyr2lat(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN replace(replace(replace(replace(replace(replace(
    translate(t, 'абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ',
                 'abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ'),
    'љ','lj'),'њ','nj'),'џ','dž'),'Љ','Lj'),'Њ','Nj'),'Џ','Dž');

-- Универсальный поисковый ключ: lower → кириллица (sr и ru) в латиницу → без диакритики;
-- đ → dj: без сербской раскладки пишут «dj» (Đorđe → djordje).
CREATE FUNCTION platform.search_norm(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN btrim(regexp_replace(
    platform.f_unaccent(
      replace(replace(replace(replace(replace(replace(replace(replace(replace(
        translate(lower(t),
                  'абвгдђежзијклмнопрстћуфхцчшёйыэъь',
                  'abvgdđežzijklmnoprstćufhcčšejye'),
        'љ','lj'),'њ','nj'),'џ','dž'),'щ','šč'),'ю','ju'),'я','ja'),'đ','dj'),'ß','ss'),'&',' ')),
    '[^a-z0-9]+', ' ', 'g'));

CREATE TEXT SEARCH CONFIGURATION platform.sr_unaccent (COPY = pg_catalog.serbian);
ALTER TEXT SEARCH CONFIGURATION platform.sr_unaccent
  ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
  WITH public.unaccent, pg_catalog.serbian_stem;

CREATE TEXT SEARCH CONFIGURATION platform.simple_unaccent (COPY = pg_catalog.simple);
ALTER TEXT SEARCH CONFIGURATION platform.simple_unaccent
  ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
  WITH public.unaccent, pg_catalog.simple;

CREATE FUNCTION platform.tsv_ru(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('pg_catalog.russian'::regconfig, coalesce(t, ''));

CREATE FUNCTION platform.tsv_sr(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('platform.sr_unaccent'::regconfig, platform.sr_cyr2lat(coalesce(t, '')));

CREATE FUNCTION platform.tsv_en(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('pg_catalog.english'::regconfig, coalesce(t, ''));

-- Язык запроса неизвестен: OR русского и сербского толкования (и английского в q_all).
CREATE FUNCTION platform.q_ru_sr(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN websearch_to_tsquery('pg_catalog.russian'::regconfig, q)
      || websearch_to_tsquery('platform.sr_unaccent'::regconfig, platform.sr_cyr2lat(q));

CREATE FUNCTION platform.q_all(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN websearch_to_tsquery('pg_catalog.russian'::regconfig, q)
      || websearch_to_tsquery('platform.sr_unaccent'::regconfig, platform.sr_cyr2lat(q))
      || websearch_to_tsquery('pg_catalog.english'::regconfig, q);

-- Префиксный вариант для подсказок: каждое слово → word:* (AND), языки через OR.
CREATE FUNCTION platform.q_prefix_ru_sr(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN (SELECT to_tsquery('pg_catalog.russian'::regconfig,
                            string_agg(quote_literal(w) || ':*', ' & '))
              || to_tsquery('platform.sr_unaccent'::regconfig,
                            string_agg(quote_literal(platform.sr_cyr2lat(w)) || ':*', ' & '))
          FROM regexp_split_to_table(btrim(regexp_replace(q, '[^[:alnum:]]+', ' ', 'g')), ' ')
               AS w
          WHERE w <> '');

CREATE AGGREGATE platform.tsvector_agg(tsvector) (
  SFUNC = pg_catalog.tsvector_concat, STYPE = tsvector, INITCOND = '');

CREATE COLLATION platform.ru_icu (provider = icu, locale = 'ru-RU');
CREATE COLLATION platform.sr_latn_icu (provider = icu, locale = 'sr-Latn-RS');
CREATE COLLATION platform.sr_cyrl_icu (provider = icu, locale = 'sr-Cyrl-RS');
CREATE COLLATION platform.num_icu (provider = icu, locale = 'und-u-kn-true');
CREATE COLLATION platform.ci_ai (provider = icu, locale = 'und-u-ks-level1', deterministic = false);
CREATE COLLATION platform.ci (provider = icu, locale = 'und-u-ks-level2', deterministic = false);
"""

DROP_SEARCH = r"""
DROP COLLATION IF EXISTS platform.ci, platform.ci_ai, platform.num_icu, platform.sr_cyrl_icu,
  platform.sr_latn_icu, platform.ru_icu;
DROP AGGREGATE IF EXISTS platform.tsvector_agg(tsvector);
DROP FUNCTION IF EXISTS platform.q_prefix_ru_sr(text), platform.q_all(text), platform.q_ru_sr(text),
  platform.tsv_en(text), platform.tsv_sr(text), platform.tsv_ru(text);
DROP TEXT SEARCH CONFIGURATION IF EXISTS platform.simple_unaccent;
DROP TEXT SEARCH CONFIGURATION IF EXISTS platform.sr_unaccent;
DROP FUNCTION IF EXISTS platform.search_norm(text), platform.sr_cyr2lat(text),
  platform.f_unaccent(text);
"""


def upgrade() -> None:
    for schema in MODULE_SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(SEARCH_FUNCTIONS)
    op.execute("CREATE SCHEMA procrastinate")
    op.execute("SET LOCAL search_path TO procrastinate")
    op.execute(SchemaManager.get_schema())
    op.execute("SET LOCAL search_path TO public, procrastinate")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS procrastinate CASCADE")
    op.execute(DROP_SEARCH)
    for schema in reversed(MODULE_SCHEMAS):
        if schema != "platform":  # в platform живёт alembic_version
            op.execute(f"DROP SCHEMA IF EXISTS {schema}")
