-- 04_trgm_typos_translit.sql — typos (pg_trgm), cross-script matching (Latin <-> Cyrillic),
-- and why FTS alone cannot do cross-language matching. Uses the taxonomy from 11_seed_reference.sql.
\pset pager off
SET search_path = mp, public;

\echo '=== A. Normalization: one "search key" for Cyrillic/Latin/no-diacritics input'
SELECT q, public.search_norm(q) AS search_key
FROM (VALUES ('Електричар'),('električar'),('elektricar'),('ЕЛЕКТРИЧАР'),('Электрик'),('elektrik'),
             ('чишћење стана'),('čišćenje stana'),('ciscenje stana'),('Ђорђе'),('Đorđe'),('Djordje'),
             ('сантехник'),('маникюр'),('manikir'),('Щётка'),('съёмка'),('veš mašina'),('веш машина')) v(q);

\echo '=== B. Typos: similarity / word_similarity / strict_word_similarity / levenshtein (on normalized keys)'
SELECT typo, correct,
       round(similarity(public.search_norm(typo), public.search_norm(correct))::numeric, 3) AS sim,
       round(word_similarity(public.search_norm(typo), public.search_norm(correct))::numeric, 3) AS word_sim,
       round(strict_word_similarity(public.search_norm(typo), public.search_norm(correct))::numeric, 3) AS strict_wsim,
       levenshtein(public.search_norm(typo), public.search_norm(correct)) AS lev
FROM (VALUES ('электирк','электрик'),('елэктрик','электрик'),('vodoinstaler','vodoinstalater'),('vodoinstalatr','vodoinstalater'),
             ('manikur','manikir'),('manikur','маникюр'),('маникур','маникюр'),('santehnik','сантехник'),('сантехникк','сантехник'),
             ('selidba','selidbe'),('prevodilac','prevodioc'),('elektrik','električar'),('электрик','električar'),
             ('moler','маляр'),('stiralka','стиральная машина')) v(typo, correct);
SHOW pg_trgm.similarity_threshold;
SHOW pg_trgm.word_similarity_threshold;

\echo '=== C. Fuzzy lookup of typos in the taxonomy (top-3 terms per typo, GiST KNN on the normalized key)'
SELECT q.typo, x.term, x.lang, c.slug AS category, round((1 - x.dist)::numeric, 3) AS sim
FROM (VALUES ('электирк'),('vodoinstaler'),('manikur'),('сантехнк'),('selidbi'),('čišćenje stanva'),('prevodioc'),('stiralka'),('moller')) q(typo)
CROSS JOIN LATERAL (
  SELECT t.term, t.lang, t.category_id, t.term_norm <-> public.search_norm(q.typo) AS dist
  FROM category_term t ORDER BY t.term_norm <-> public.search_norm(q.typo) LIMIT 3) x
JOIN category c ON c.id = x.category_id
ORDER BY q.typo, x.dist;

\echo '=== D. Cross-script: Latin query vs Cyrillic content and vice versa'
SELECT q AS query, d AS content,
       to_tsvector('serbian', d) @@ websearch_to_tsquery('serbian', q) AS fts_serbian_plain,
       public.tsv_sr(d) @@ websearch_to_tsquery('public.sr_unaccent', public.sr_cyr2lat(q)) AS fts_sr_translit_unaccent,
       public.search_norm(d) LIKE '%' || public.search_norm(q) || '%' AS key_substring,
       round(word_similarity(public.search_norm(q), public.search_norm(d))::numeric, 2) AS key_word_sim
FROM (VALUES ('elektricar','Електричар за хитне интервенције'),('električar','Електричар за хитне интервенције'),
             ('електричар','Električar Beograd'),('ciscenje','Генерално чишћење станова'),('чишћење','Ciscenje stanova povoljno'),
             ('vodoinstalater','Водоинсталатер 0-24')) v(q, d);

\echo '=== E. Cross-LANGUAGE (ru query vs sr content): FTS alone cannot match, taxonomy can'
SELECT q AS query_ru, d AS content_sr,
       public.tsv_ru(d) || public.tsv_sr(d) @@ public.q_all(q) AS fts_any_config,
       round(similarity(public.search_norm(q), public.search_norm(d))::numeric, 2) AS trgm_on_translit
FROM (VALUES ('электрик','Električar'),('сантехник','Vodoinstalater'),('маляр','Moler'),('маникюр','Manikir'),
             ('переезд','Selidbe'),('переводчик','Prevodilac'),('уборка квартиры','Čišćenje stana')) v(q, d);
\echo '-- taxonomy lookup: term (any language/script) -> category -> names in all languages'
SELECT q AS query, c.slug, c.name->>'ru' AS ru, c.name->>'sr-Latn' AS sr_latn, c.name->>'sr-Cyrl' AS sr_cyrl, c.name->>'en' AS en
FROM (VALUES ('электрик'),('električar'),('електричар'),('elektricar'),('сантехник'),('vodoinstalater'),('маляр'),('moler'),
             ('стиралка'),('veš mašina'),('муж на час'),('majstor za sve'),('боравак'),('внж')) v(q)
JOIN LATERAL (SELECT DISTINCT category_id FROM category_term t WHERE t.term_norm = public.search_norm(v.q)) m ON true
JOIN category c ON c.id = m.category_id
ORDER BY 1;
