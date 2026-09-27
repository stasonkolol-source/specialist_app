-- 06_i18n_collations.sql — multilingual content: JSONB vs translation table, fallback languages,
-- ICU collations for ru / sr-Latn / sr-Cyrl, nondeterministic (case/accent-insensitive) collations.
\pset pager off
SET search_path = mp, public;
SET max_parallel_workers_per_gather = 0;

\echo '=== A. ICU availability'
SELECT (SELECT count(*) FROM pg_collation WHERE collprovider = 'i') AS icu_collations,
       (SELECT string_agg(collname, ', ' ORDER BY collname) FROM pg_collation
         WHERE collname IN ('ru-RU-x-icu','sr-Latn-RS-x-icu','sr-Cyrl-RS-x-icu','sr-x-icu','hr-HR-x-icu','und-x-icu')) AS predefined,
       icu_unicode_version() AS icu_unicode, unicode_version() AS pg_unicode;

CREATE COLLATION IF NOT EXISTS public.ru_icu      (provider = icu, locale = 'ru-RU');
CREATE COLLATION IF NOT EXISTS public.sr_latn_icu (provider = icu, locale = 'sr-Latn-RS');
CREATE COLLATION IF NOT EXISTS public.sr_cyrl_icu (provider = icu, locale = 'sr-Cyrl-RS');
CREATE COLLATION IF NOT EXISTS public.num_icu     (provider = icu, locale = 'und-u-kn-true');                  -- natural numbers
CREATE COLLATION IF NOT EXISTS public.ci_ai       (provider = icu, locale = 'und-u-ks-level1', deterministic = false); -- case+accent insensitive
CREATE COLLATION IF NOT EXISTS public.ci          (provider = icu, locale = 'und-u-ks-level2', deterministic = false); -- case insensitive only

\echo '=== B. Sorting: C (code point) vs ICU'
SELECT 'sr-Latn' AS alphabet, string_agg(w, ' ' ORDER BY w COLLATE "C") AS c_order, string_agg(w, ' ' ORDER BY w COLLATE sr_latn_icu) AS icu_order
FROM unnest('{zima,žaba,šuma,sat,nož,njiva,lopta,ljubav,đak,džem,dan,ćup,čaj,cvet,Čačak,Beograd}'::text[]) w
UNION ALL
SELECT 'sr-Cyrl', string_agg(w, ' ' ORDER BY w COLLATE "C"), string_agg(w, ' ' ORDER BY w COLLATE sr_cyrl_icu)
FROM unnest('{зима,жаба,шума,сат,нож,њива,лопта,љубав,ђак,џем,дан,ћуп,чај,цвет,Чачак,Београд}'::text[]) w
UNION ALL
SELECT 'ru', string_agg(w, ' ' ORDER BY w COLLATE "C"), string_agg(w, ' ' ORDER BY w COLLATE ru_icu)
FROM unnest('{яблоко,Яблоко,ёж,ель,еда,Ёлка,елка,жук,Электрик,электрик,Ъ}'::text[]) w
UNION ALL
SELECT 'natural', string_agg(w, ' | ' ORDER BY w COLLATE "C"), string_agg(w, ' | ' ORDER BY w COLLATE num_icu)
FROM unnest('{zona 10,zona 2,zona 1,zona 21}'::text[]) w;

\echo '=== C. Nondeterministic collations: equality and (PG18) LIKE, case/accent-insensitive'
SELECT 'Čačak' = 'cacak' COLLATE ci_ai AS eq_ci_ai, 'Čačak' = 'čačak' COLLATE ci AS eq_ci, 'Čačak' = 'cacak' COLLATE ci AS eq_ci_accent,
       'ЧАЧАК' = 'чачак' COLLATE ci_ai AS eq_cyr_case, 'Чачак' = 'Čačak' COLLATE ci_ai AS eq_cross_script,
       'Električar Beograd' LIKE 'elektricar%' COLLATE ci_ai AS like_ci_ai_pg18;
\echo '-- btree index on a nondeterministic collation supports equality lookups (not LIKE prefix)'
DROP TABLE IF EXISTS coll_demo; CREATE TEMP TABLE coll_demo(city text COLLATE ci_ai);
INSERT INTO coll_demo SELECT name->>'sr-Latn' FROM city;
CREATE INDEX ON coll_demo (city); ANALYZE coll_demo; SET enable_seqscan = off;
EXPLAIN (COSTS OFF) SELECT * FROM coll_demo WHERE city = 'cacak';
SELECT * FROM coll_demo WHERE city = 'CACAK' OR city = 'nis';
RESET enable_seqscan;

\echo '=== D. Reference data (300 categories): JSONB vs translation table, UI locale sr-Cyrl with fallback sr-Cyrl > sr-Latn > en > ru'
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT id, label FROM (
  SELECT id, coalesce(name->>'sr-Cyrl', name->>'sr-Latn', name->>'en', name->>'ru') AS label FROM category) x
ORDER BY label COLLATE sr_cyrl_icu;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT c.id, t.name
FROM category c
CROSS JOIN LATERAL (SELECT tr.name FROM category_translation tr WHERE tr.category_id = c.id AND tr.locale = ANY ('{sr-Cyrl,sr-Latn,en,ru}')
                    ORDER BY array_position('{sr-Cyrl,sr-Latn,en,ru}'::text[], tr.locale) LIMIT 1) t
ORDER BY t.name COLLATE sr_cyrl_icu;

\echo '=== E. Scale test: 200k items, 4 locales, ~10% missing sr-Cyrl (fallback needed)'
DROP TABLE IF EXISTS i18n_item_json, i18n_item_tr;
SELECT setseed(0.7);
CREATE TABLE i18n_item_json AS
SELECT n AS id,
       jsonb_strip_nulls(jsonb_build_object(
         'ru', (c.name->>'ru') || ' №' || n,
         'sr-Latn', (c.name->>'sr-Latn') || ' br. ' || n,
         'sr-Cyrl', CASE WHEN random() < 0.9 THEN (c.name->>'sr-Cyrl') || ' бр. ' || n END,
         'en', (c.name->>'en') || ' #' || n)) AS name
FROM generate_series(1, 200000) n JOIN category c ON c.id = 1 + (n % 300);
ALTER TABLE i18n_item_json ADD PRIMARY KEY (id);
CREATE TABLE i18n_item_tr AS SELECT i.id AS item_id, kv.key AS locale, kv.value AS name FROM i18n_item_json i, jsonb_each_text(i.name) kv;
ALTER TABLE i18n_item_tr ADD PRIMARY KEY (item_id, locale);
VACUUM ANALYZE i18n_item_json; VACUUM ANALYZE i18n_item_tr;
SELECT pg_size_pretty(pg_total_relation_size('i18n_item_json')) AS json_total, pg_size_pretty(pg_total_relation_size('i18n_item_tr')) AS tr_total,
       (SELECT count(*) FROM i18n_item_tr) AS tr_rows;

\echo '-- E1 JSONB: first page sorted by localized label with fallback, no index (full sort)'
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT id, label FROM (SELECT id, coalesce(name->>'sr-Cyrl', name->>'sr-Latn') AS label FROM i18n_item_json) x ORDER BY label COLLATE sr_cyrl_icu LIMIT 50;
\echo '-- E2 JSONB + expression index on the fallback expression with ICU collation'
CREATE INDEX i18n_json_label_sr_cyrl ON i18n_item_json ((coalesce(name->>'sr-Cyrl', name->>'sr-Latn') COLLATE sr_cyrl_icu));
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT id, coalesce(name->>'sr-Cyrl', name->>'sr-Latn') AS label FROM i18n_item_json ORDER BY coalesce(name->>'sr-Cyrl', name->>'sr-Latn') COLLATE sr_cyrl_icu LIMIT 50;
\echo '-- E3 translation table: fallback via DISTINCT ON, then sort (full scan)'
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT item_id, name FROM (
  SELECT DISTINCT ON (item_id) item_id, name FROM i18n_item_tr WHERE locale IN ('sr-Cyrl','sr-Latn')
  ORDER BY item_id, array_position('{sr-Cyrl,sr-Latn}'::text[], locale)) x
ORDER BY name COLLATE sr_cyrl_icu LIMIT 50;
\echo '-- E4 translation table, single locale (no fallback) + index (locale, name COLLATE sr_cyrl_icu)'
CREATE INDEX i18n_tr_locale_name ON i18n_item_tr (locale, (name COLLATE sr_cyrl_icu));
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT item_id, name FROM i18n_item_tr WHERE locale = 'sr-Cyrl' ORDER BY name COLLATE sr_cyrl_icu LIMIT 50;
\echo '-- E5 cost of ICU vs C collation in a full sort of 200k labels'
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON) SELECT l FROM (SELECT name->>'ru' AS l FROM i18n_item_json) x ORDER BY l COLLATE ru_icu OFFSET 199990;
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON) SELECT l FROM (SELECT name->>'ru' AS l FROM i18n_item_json) x ORDER BY l COLLATE "C" OFFSET 199990;
\echo '-- E6 point lookup: item by exact localized name'
CREATE INDEX i18n_json_name_gin ON i18n_item_json USING gin (name jsonb_path_ops);
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON) SELECT id FROM i18n_item_json WHERE name @> '{"sr-Latn": "Električar br. 45"}';
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON) SELECT item_id FROM i18n_item_tr WHERE locale = 'sr-Latn' AND name = 'Električar br. 45';
\echo '-- E7 required locales enforced by CHECK on JSONB'
ALTER TABLE i18n_item_json ADD CONSTRAINT name_has_required CHECK (name ?& '{ru,sr-Latn}');
SELECT pg_size_pretty(pg_relation_size('i18n_json_label_sr_cyrl')) AS json_expr_idx, pg_size_pretty(pg_relation_size('i18n_tr_locale_name')) AS tr_idx,
       pg_size_pretty(pg_relation_size('i18n_json_name_gin')) AS json_gin;
DROP TABLE i18n_item_json, i18n_item_tr;
