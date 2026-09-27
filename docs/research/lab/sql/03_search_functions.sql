-- 03_search_functions.sql — canonical, idempotent search helpers used by the schema.
-- Everything is IMMUTABLE + schema-qualified so it can be used in generated columns and indexes
-- and survives pg_dump/restore (restore runs with an empty search_path).
\set ON_ERROR_STOP 1

-- 1) IMMUTABLE unaccent wrapper (unaccent() itself is STABLE). SQL-standard body (PG14+) binds
--    the dictionary at creation time and records a dependency on it.
CREATE OR REPLACE FUNCTION public.f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN public.unaccent('public.unaccent'::regdictionary, $1);

-- 2) Serbian Cyrillic -> Serbian Latin (gaj), 1:1 mapping incl. digraph letters.
CREATE OR REPLACE FUNCTION public.sr_cyr2lat(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN replace(replace(replace(replace(replace(replace(
    translate(t, 'абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ',
                 'abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ'),
    'љ','lj'),'њ','nj'),'џ','dž'),'Љ','Lj'),'Њ','Nj'),'Џ','Dž');

-- 3) Universal "search key": lower -> any Cyrillic (sr + ru letters) -> Latin -> strip diacritics.
--    електричар / električar / elektricar -> 'elektricar';  электрик -> 'elektrik';  сантехник -> 'santehnik'
--    đ -> 'dj' because Serbian users without a Serbian keyboard type "dj" (Đorđe -> djordje).
CREATE OR REPLACE FUNCTION public.search_norm(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN btrim(regexp_replace(
    public.f_unaccent(
      replace(replace(replace(replace(replace(replace(replace(replace(replace(
        translate(lower(t),
                  'абвгдђежзијклмнопрстћуфхцчшёйыэъь',
                  'abvgdđežzijklmnoprstćufhcčšejye'),        -- ъ ь have no counterpart -> removed
        'љ','lj'),'њ','nj'),'џ','dž'),'щ','šč'),'ю','ju'),'я','ja'),'đ','dj'),'ß','ss'),'&',' ')),
    '[^a-z0-9]+', ' ', 'g'));

-- 4) Text search configurations.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_ts_config WHERE cfgname = 'sr_unaccent' AND cfgnamespace = 'public'::regnamespace) THEN
    CREATE TEXT SEARCH CONFIGURATION public.sr_unaccent (COPY = pg_catalog.serbian);
    ALTER TEXT SEARCH CONFIGURATION public.sr_unaccent
      ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
      WITH public.unaccent, pg_catalog.serbian_stem;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_ts_config WHERE cfgname = 'simple_unaccent' AND cfgnamespace = 'public'::regnamespace) THEN
    CREATE TEXT SEARCH CONFIGURATION public.simple_unaccent (COPY = pg_catalog.simple);
    ALTER TEXT SEARCH CONFIGURATION public.simple_unaccent
      ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
      WITH public.unaccent, pg_catalog.simple;
  END IF;
END $$;

-- 5) Document helpers (per language) and query helper (language of the query is unknown ->
--    OR of the Russian and the Serbian interpretation; English optional).
CREATE OR REPLACE FUNCTION public.tsv_ru(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('pg_catalog.russian'::regconfig, coalesce(t, ''));
CREATE OR REPLACE FUNCTION public.tsv_sr(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('public.sr_unaccent'::regconfig, public.sr_cyr2lat(coalesce(t, '')));
CREATE OR REPLACE FUNCTION public.q_ru_sr(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN websearch_to_tsquery('pg_catalog.russian'::regconfig, q)
      || websearch_to_tsquery('public.sr_unaccent'::regconfig, public.sr_cyr2lat(q));
-- prefix variant for search-as-you-type: every word becomes word:* (AND), both languages OR-ed
CREATE OR REPLACE FUNCTION public.q_prefix_ru_sr(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN (SELECT to_tsquery('pg_catalog.russian'::regconfig, string_agg(quote_literal(w) || ':*', ' & '))
              || to_tsquery('public.sr_unaccent'::regconfig, string_agg(quote_literal(public.sr_cyr2lat(w)) || ':*', ' & '))
          FROM regexp_split_to_table(btrim(regexp_replace(q, '[^[:alnum:]]+', ' ', 'g')), ' ') AS w
          WHERE w <> '');

SELECT public.search_norm('Електричар Čišćenje ЂУРЂЕВДАН Щётка съёмка') AS search_norm_demo,
       public.q_ru_sr('ремонт стиральной машины') AS q_demo,
       public.q_prefix_ru_sr('popravka veš maš') AS q_prefix_demo;

-- 6) Query helper incl. English (read-model documents also contain English category names/texts)
CREATE OR REPLACE FUNCTION public.q_all(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN websearch_to_tsquery('pg_catalog.russian'::regconfig, q)
      || websearch_to_tsquery('public.sr_unaccent'::regconfig, public.sr_cyr2lat(q))
      || websearch_to_tsquery('pg_catalog.english'::regconfig, q);
CREATE OR REPLACE FUNCTION public.tsv_en(t text) RETURNS tsvector
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN to_tsvector('pg_catalog.english'::regconfig, coalesce(t, ''));

-- 7) tsvector aggregate (|| over rows); positions of later vectors are shifted like with ||
CREATE OR REPLACE AGGREGATE public.tsvector_agg(tsvector) (
  SFUNC = pg_catalog.tsvector_concat, STYPE = tsvector, INITCOND = '');
