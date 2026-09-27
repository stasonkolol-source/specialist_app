-- 02_fts_ru_sr.sql — Full-text search for Russian and Serbian (Latin + Cyrillic).
\pset pager off
\set ON_ERROR_STOP 0
SET client_min_messages = warning;

\echo '=== A. Built-in configs on realistic phrases'
DROP TABLE IF EXISTS fts_phrase;
CREATE TEMP TABLE fts_phrase(id int, lang text, phrase text);
INSERT INTO fts_phrase VALUES
 (1,'ru','электрик'),(2,'ru','сантехник'),(3,'ru','ремонт стиральной машины'),(4,'ru','маникюр'),
 (5,'sr-Latn','električar'),(6,'sr-Cyrl','електричар'),(7,'sr-Latn','vodoinstalater'),(8,'sr-Cyrl','водоинсталатер'),
 (9,'sr-Latn','čišćenje stana'),(10,'sr-Cyrl','чишћење стана'),(11,'sr-Latn','popravka veš mašine'),
 (12,'sr-Latn','majstor za klime'),(13,'sr-Latn','selidbe'),(14,'sr-Latn','prevodilac'),
 (15,'sr-Latn(no diacritics)','ciscenje stana'),(16,'sr-Latn(no diacritics)','popravka ves masine'),
 (17,'sr-Latn','električari, vodoinstalateri i moleri'),(18,'ru','ремонт стиральных машин, электрики');
SELECT id, lang, phrase,
       to_tsvector('russian', phrase)::text AS russian,
       to_tsvector('serbian', phrase)::text AS serbian,
       to_tsvector('simple',  phrase)::text AS simple
FROM fts_phrase ORDER BY id;

\echo '=== B. Serbian stemmer transliterates Cyrillic -> Latin (with diacritics); no Serbian stopword list'
SELECT dictname, dictinitoption FROM pg_ts_dict WHERE dictname IN ('serbian_stem','russian_stem');
SELECT ts_lexize('serbian_stem','чишћење') AS cyr, ts_lexize('serbian_stem','čišćenje') AS lat,
       ts_lexize('serbian_stem','ciscenje') AS ascii_, ts_lexize('serbian_stem','za') AS stopword_za,
       ts_lexize('russian_stem','и') AS ru_stopword_i;


\echo '-- B2: Serbian stemmer is a light stemmer: some inflected forms do not collapse'
SELECT w, ts_lexize('serbian_stem', w) AS stem FROM (VALUES ('stan'),('stana'),('stanu'),('stanom'),('stanovi'),('stanova'),
  ('majstor'),('majstora'),('majstori'),('majstorima'),('mašina'),('mašine'),('mašinu'),('mašinama'),
  ('čišćenje'),('čišćenja'),('čišćenju'),('klima'),('klime'),('klimu'),('električar'),('električara'),('električari')) v(w);
\echo '=== C. unaccent behaviour on Serbian diacritics and Cyrillic'
SELECT unaccent('čćšžđ ČĆŠŽĐ dž Dž') AS sr_latin,
       unaccent('ђ ћ ч ш ж џ љ њ ј') AS sr_cyrillic,
       unaccent('ёлка йогурт Ё Й') AS ru_cyrillic;

\echo '=== D. IMMUTABLE problem: unaccent() is STABLE'
SELECT p.oid::regprocedure AS fn, p.provolatile AS volatility
FROM pg_proc p WHERE p.proname IN ('unaccent','to_tsvector','websearch_to_tsquery') ORDER BY 1::text;
DROP TABLE IF EXISTS imm_test;
CREATE TABLE imm_test(id int, title text);
\echo '-- D1 expected ERROR: index on unaccent()'
CREATE INDEX imm_test_bad_idx ON imm_test USING gin (to_tsvector('simple', unaccent(title)));
\echo '-- D2 expected ERROR: generated column with unaccent()'
ALTER TABLE imm_test ADD COLUMN tsv_bad tsvector GENERATED ALWAYS AS (to_tsvector('simple', unaccent(title))) STORED;
\echo '-- D3 workaround: IMMUTABLE SQL-standard-body wrapper with schema-qualified dictionary (PG14+)'
CREATE OR REPLACE FUNCTION public.f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN public.unaccent('public.unaccent'::regdictionary, $1);
ALTER TABLE imm_test ADD COLUMN title_norm text GENERATED ALWAYS AS (lower(public.f_unaccent(title))) STORED;
CREATE INDEX imm_test_trgm_idx ON imm_test USING gin (title_norm gin_trgm_ops);
CREATE INDEX imm_test_expr_idx ON imm_test USING gin (to_tsvector('simple', public.f_unaccent(title)));
INSERT INTO imm_test(id, title) VALUES (1, 'Čišćenje stanova Đurđevdan');
SELECT * FROM imm_test;
\echo '-- D4 workaround 2: text search configuration that contains the unaccent dictionary.'
\echo '--    to_tsvector(regconfig, text) is IMMUTABLE, so it is accepted in generated columns/indexes.'

\echo '=== E. Custom configurations'
DROP TEXT SEARCH CONFIGURATION IF EXISTS public.sr_unaccent;
CREATE TEXT SEARCH CONFIGURATION public.sr_unaccent (COPY = pg_catalog.serbian);
ALTER TEXT SEARCH CONFIGURATION public.sr_unaccent
  ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
  WITH public.unaccent, pg_catalog.serbian_stem;
DROP TEXT SEARCH CONFIGURATION IF EXISTS public.simple_unaccent;
CREATE TEXT SEARCH CONFIGURATION public.simple_unaccent (COPY = pg_catalog.simple);
ALTER TEXT SEARCH CONFIGURATION public.simple_unaccent
  ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
  WITH public.unaccent, pg_catalog.simple;

-- Serbian Cyrillic -> Latin transliteration (1:1 incl. digraph letters љ њ џ). IMMUTABLE, no extensions.
CREATE OR REPLACE FUNCTION public.sr_cyr2lat(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN replace(replace(replace(replace(replace(replace(
    translate(t, 'абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ',
                 'abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ'),
    'љ','lj'),'њ','nj'),'џ','dž'),'Љ','Lj'),'Њ','Nj'),'Џ','Dž');

\echo '-- E1: unaccent BEFORE the Serbian stemmer is not enough for Cyrillic input:'
\echo '--     unaccent sees Cyrillic (no-op), then the stemmer transliterates and re-introduces diacritics'
SELECT to_tsvector('sr_unaccent', 'електричар čišćenje чишћење') AS sr_unaccent_raw,
       to_tsvector('sr_unaccent', public.sr_cyr2lat('електричар čišćenje чишћење')) AS sr_unaccent_translit;

\echo '-- E3: websearch AND-semantics + light stemming -> zero hits for "čišćenje stana" vs content "čišćenje stanova"'
SELECT websearch_to_tsquery('sr_unaccent','čišćenje stana') AS q_and,
       to_tsvector('sr_unaccent','Generalno čišćenje stanova') @@ websearch_to_tsquery('sr_unaccent','čišćenje stana') AS and_match,
       to_tsvector('sr_unaccent','Generalno čišćenje stanova') @@ to_tsquery('sr_unaccent','ciscenj:* & stan:*') AS prefix_and_match;

\echo '-- E2: match matrix document x query (true = @@ matches)'
DROP TABLE IF EXISTS mm_doc; DROP TABLE IF EXISTS mm_q;
CREATE TEMP TABLE mm_doc(d text); CREATE TEMP TABLE mm_q(q text);
INSERT INTO mm_doc VALUES ('Čišćenje stana'),('Чишћење стана'),('ciscenje stana'),('Električar'),('Електричар'),('Popravka veš mašine');
INSERT INTO mm_q   VALUES ('čišćenje'),('чишћење'),('ciscenje'),('ČIŠĆENJE STANOVA'),('elektricar'),('електричар'),('ves masina'),('веш машина');
SELECT q, d,
  to_tsvector('serbian', d) @@ websearch_to_tsquery('serbian', q) AS serbian,
  to_tsvector('sr_unaccent', d) @@ websearch_to_tsquery('sr_unaccent', q) AS sr_unacc,
  to_tsvector('sr_unaccent', public.sr_cyr2lat(d)) @@ websearch_to_tsquery('sr_unaccent', public.sr_cyr2lat(q)) AS sr_unacc_translit
FROM mm_q CROSS JOIN mm_doc
WHERE (q ILIKE '%ci%' OR q ILIKE '%чи%' OR q ILIKE '%Č%') AND (d ILIKE '%či%' OR d ILIKE '%чи%' OR d ILIKE '%ci%' OR d ILIKE '%Či%')
   OR (q ILIKE '%lek%' OR q ILIKE '%лек%') AND (d ILIKE '%lek%' OR d ILIKE '%лек%')
   OR (q ILIKE '%ves%' OR q ILIKE '%веш%') AND d ILIKE '%maš%'
ORDER BY q, d;

\echo '=== F. Russian + Serbian in one document'
DROP TABLE IF EXISTS fts_doc;
CREATE TABLE fts_doc (
  id int PRIMARY KEY,
  title_ru text, title_sr text, body_ru text, body_sr text,
  tsv tsvector GENERATED ALWAYS AS (
       setweight(to_tsvector('russian', coalesce(title_ru,'')), 'A')
    || setweight(to_tsvector('sr_unaccent', public.sr_cyr2lat(coalesce(title_sr,''))), 'A')
    || setweight(to_tsvector('russian', coalesce(body_ru,'')), 'C')
    || setweight(to_tsvector('sr_unaccent', public.sr_cyr2lat(coalesce(body_sr,''))), 'C')) STORED
);
CREATE INDEX fts_doc_tsv_idx ON fts_doc USING gin (tsv);
INSERT INTO fts_doc(id,title_ru,title_sr,body_ru,body_sr) VALUES
 (1,'Электрик','Električar','Замена розеток, монтаж проводки, установка люстр','Zamena utičnica, električne instalacije, montaža lustera'),
 (2,'Сантехник',NULL,'Устранение протечек, установка смесителей и бойлеров',NULL),
 (3,NULL,'Водоинсталатер',NULL,'Поправка славина, уградња бојлера, одгушење канализације'),
 (4,'Ремонт стиральных машин','Popravka veš mašina','Ремонт стиральных и посудомоечных машин на дому','Servis veš mašina i sudomašina, dolazak na adresu'),
 (5,NULL,'Čišćenje stanova',NULL,'Generalno čišćenje stanova i kuća, pranje prozora'),
 (6,'Маникюр и педикюр','Manikir i pedikir','Аппаратный маникюр, покрытие гель-лаком','Gel lak, manikir, pedikir'),
 (7,'Мастер на час','Majstor za sve','Мелкий ремонт, сборка мебели, электрика','Sitne popravke, montaža nameštaja, majstor za klime'),
 (8,NULL,'Selidbe Beograd',NULL,'Selidbe stanova i kancelarija, prevoz nameštaja'),
 (9,'Переводчик сербского','Prevodilac',' Переводы документов, присяжный перевод','Sudski tumač za ruski jezik, prevodilac');
-- query: OR of both language interpretations of the same user input
CREATE OR REPLACE FUNCTION public.q_ru_sr(q text) RETURNS tsquery
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN websearch_to_tsquery('russian', q) || websearch_to_tsquery('sr_unaccent', public.sr_cyr2lat(q));
SELECT q, public.q_ru_sr(q)::text AS tsquery,
       (SELECT string_agg(id::text, ',' ORDER BY ts_rank_cd(tsv, public.q_ru_sr(q)) DESC, id) FROM fts_doc WHERE tsv @@ public.q_ru_sr(q)) AS matched_ids_by_rank_cd
FROM (VALUES ('электрик'),('электрика'),('električar'),('elektricar'),('електричар'),('сантехник'),('vodoinstalater'),('водоинсталатер'),
             ('ремонт стиральной машины'),('popravka veš mašine'),('popravka ves masine'),('маникюр'),('manikir'),('čišćenje stana'),
             ('чишћење стана'),('ciscenje stanova'),('majstor za klime'),('selidbe'),('prevodilac'),('перевод документов'),
             ('"ремонт стиральных"'),('электрик -люстр'),('manikir or pedikir')) v(q);

\echo '=== G. Choosing the configuration by content language (regconfig column)'
DROP TABLE IF EXISTS fts_lang_doc;
CREATE TABLE fts_lang_doc(
  id int, lang text, body text,
  cfg regconfig GENERATED ALWAYS AS (CASE lang WHEN 'ru' THEN 'russian'::regconfig WHEN 'en' THEN 'english'::regconfig ELSE 'sr_unaccent'::regconfig END) STORED,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector(CASE lang WHEN 'ru' THEN 'russian'::regconfig WHEN 'en' THEN 'english'::regconfig ELSE 'sr_unaccent'::regconfig END,
                                               CASE WHEN lang LIKE 'sr%' THEN public.sr_cyr2lat(body) ELSE body END)) STORED);
INSERT INTO fts_lang_doc(id, lang, body) VALUES (1,'ru','Ремонт стиральных машин'),(2,'sr-Cyrl','Поправка веш машина'),(3,'sr-Latn','Popravka veš mašina'),(4,'en','Washing machine repairs');
SELECT id, lang, cfg, tsv FROM fts_lang_doc;

\echo '=== H. websearch_to_tsquery syntax'
SELECT q, websearch_to_tsquery('russian', q) AS ru, websearch_to_tsquery('sr_unaccent', public.sr_cyr2lat(q)) AS sr
FROM (VALUES ('электрик -люстра'),('"ремонт стиральной машины"'),('vodoinstalater or moler'),('čišćenje -prozora'),('маникюр гель-лак')) v(q);

\echo '=== I. Prefix search for autocomplete (to_tsquery with :*)'
SELECT q, to_tsquery('russian', q || ':*') AS ru_prefix, to_tsquery('sr_unaccent', public.sr_cyr2lat(q) || ':*') AS sr_prefix,
       (SELECT string_agg(id::text, ',') FROM fts_doc WHERE tsv @@ (to_tsquery('russian', q || ':*') || to_tsquery('sr_unaccent', public.sr_cyr2lat(q) || ':*'))) AS matched
FROM (VALUES ('элек'),('электри'),('сантех'),('стиральн'),('стиральной'),('vodoinst'),('водоинст'),('čišć'),('cisc'),('mani'),('selid'),('prevod')) v(q);
\echo '-- pitfall: stemming the prefix of a full word can over-cut; stem-then-prefix vs simple prefix'
SELECT to_tsquery('russian','стиральной:*') AS stemmed_prefix, to_tsquery('simple','стиральной:*') AS simple_prefix;

\echo '=== J. Ranking: ts_rank vs ts_rank_cd, weights (A=title, C=body) and normalization'
\echo '-- J1 single-term query: title hit (A) must outrank body-only hit (C)'
SELECT id, title_ru,
  round(ts_rank(tsv, q)::numeric, 4) AS rank, round(ts_rank(tsv, q, 32)::numeric, 4) AS rank_n32,
  round(ts_rank_cd(tsv, q)::numeric, 4) AS rank_cd, round(ts_rank_cd(tsv, q, 32)::numeric, 4) AS rank_cd_n32,
  round(ts_rank_cd('{0.05,0.1,0.3,1.0}', tsv, q, 32)::numeric, 4) AS rank_cd_custom_w
FROM fts_doc, public.q_ru_sr('ремонт') q WHERE tsv @@ q ORDER BY rank_cd DESC;
\echo '-- J2 OR-query over several words: coverage + weights'
SELECT id, title_ru, title_sr,
  round(ts_rank(tsv, q)::numeric, 4) AS rank, round(ts_rank_cd(tsv, q)::numeric, 4) AS rank_cd,
  round(ts_rank_cd(tsv, q, 1)::numeric, 4) AS rank_cd_n1_loglen
FROM fts_doc, public.q_ru_sr('электрик or ремонт or мебель or popravka or nameštaj') q
WHERE tsv @@ q ORDER BY rank_cd DESC, rank DESC;
\echo '-- J3 ts_rank_cd is 0 for a document that does not satisfy the (AND) query; ts_rank gives partial credit'
SELECT id, round(ts_rank(tsv, q)::numeric,4) AS rank, round(ts_rank_cd(tsv, q)::numeric,4) AS rank_cd, tsv @@ q AS matches
FROM fts_doc, websearch_to_tsquery('russian','ремонт машин электрика') q WHERE id IN (1,4,7) ORDER BY id;

\echo '=== K. Headline / snippet'
SELECT id, ts_headline('russian', body_ru, websearch_to_tsquery('russian','ремонт машин'), 'StartSel=<b>,StopSel=</b>,MaxWords=12,MinWords=4') AS headline
FROM fts_doc WHERE id IN (4,7);
