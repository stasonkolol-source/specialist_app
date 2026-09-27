-- 14_readmodel.sql — denormalized search read-model for specialists (one row per specialist).
--  * category_ids  = own leaf categories + ALL ancestors  -> "category with descendants" is  category_ids @> '{id}'
--  * search_tsv    = own texts (ru/sr/en) + taxonomy names/synonyms of own categories in ALL languages
--                    (enrichment makes a Russian query find a Serbian-only profile and vice versa)
--  * search_tsv_own= own texts only (for the enrichment comparison)
--  * price range over active services, score = Bayesian average of the rating
\set ON_ERROR_STOP 1
\timing on
SET search_path = mp, public;

-- per-category document parts, computed once (300 rows)
DROP TABLE IF EXISTS category_doc CASCADE;
CREATE TABLE category_doc AS
SELECT c.id AS category_id,
       setweight(public.tsv_ru(c.name->>'ru') || public.tsv_sr(c.name->>'sr-Latn') || public.tsv_en(c.name->>'en'), 'A') AS tsv_names,
       setweight(public.tsv_ru(string_agg(t.term, ' ; ') FILTER (WHERE t.lang = 'ru' AND t.kind = 'synonym'))
              || public.tsv_sr(string_agg(t.term, ' ; ') FILTER (WHERE t.lang = 'sr-Latn' AND t.kind = 'synonym'))
              || public.tsv_en(string_agg(t.term, ' ; ') FILTER (WHERE t.lang = 'en' AND t.kind = 'synonym')), 'B') AS tsv_synonyms
FROM category c LEFT JOIN category_term t ON t.category_id = c.id
GROUP BY c.id;
ALTER TABLE category_doc ADD PRIMARY KEY (category_id);

CREATE OR REPLACE VIEW v_specialist_search_src AS
SELECT s.id AS specialist_id, s.city_id, s.district_id, s.location, s.travels, s.travel_radius_m, s.languages,
       cats.category_ids, cats.leaf_ids,
       pr.price_min_rsd, pr.price_max_rsd,
       s.rating, s.reviews_count,
       ((coalesce(s.rating, 0) * s.reviews_count + 3.8 * 3) / (s.reviews_count + 3))::real AS score,
       s.available_on, s.display_name,
       setweight(to_tsvector('public.simple_unaccent'::regconfig, public.sr_cyr2lat(s.display_name)), 'A')
         || cats.tsv_cat
         || setweight(public.tsv_ru(pr.titles_ru) || public.tsv_sr(pr.titles_sr), 'C')
         || setweight(public.tsv_ru(s.about->>'ru') || public.tsv_sr(concat_ws(' ', s.about->>'sr-Latn', s.about->>'sr-Cyrl'))
                      || public.tsv_en(s.about->>'en'), 'D') AS search_tsv,
       setweight(to_tsvector('public.simple_unaccent'::regconfig, public.sr_cyr2lat(s.display_name)), 'A')
         || setweight(public.tsv_ru(pr.titles_ru) || public.tsv_sr(pr.titles_sr), 'C')
         || setweight(public.tsv_ru(s.about->>'ru') || public.tsv_sr(concat_ws(' ', s.about->>'sr-Latn', s.about->>'sr-Cyrl'))
                      || public.tsv_en(s.about->>'en'), 'D') AS search_tsv_own,
       now() AS refreshed_at
FROM specialist s
CROSS JOIN LATERAL (
  SELECT array_agg(DISTINCT a.id ORDER BY a.id) AS category_ids,
         array_agg(DISTINCT l.id ORDER BY l.id) AS leaf_ids,
         (SELECT public.tsvector_agg(d.tsv_names || d.tsv_synonyms)
            FROM category_doc d WHERE d.category_id = ANY (array_agg(DISTINCT l.id))) AS tsv_cat
  FROM specialist_category sc
  JOIN category l ON l.id = sc.category_id
  JOIN category a ON a.path @> l.path
  WHERE sc.specialist_id = s.id
) cats
CROSS JOIN LATERAL (
  SELECT min(sv.price_rsd) AS price_min_rsd, max(coalesce(sv.price_to_rsd, sv.price_rsd)) AS price_max_rsd,
         string_agg(sv.title, ' ; ') FILTER (WHERE sv.lang = 'ru') AS titles_ru,
         string_agg(sv.title, ' ; ') FILTER (WHERE sv.lang <> 'ru') AS titles_sr
  FROM service sv WHERE sv.specialist_id = s.id AND sv.is_active
) pr
WHERE s.status = 'active';

-- full build
DROP TABLE IF EXISTS specialist_search;
CREATE TABLE specialist_search AS SELECT * FROM v_specialist_search_src;
ALTER TABLE specialist_search ADD PRIMARY KEY (specialist_id);
ALTER TABLE specialist_search ALTER COLUMN category_ids SET NOT NULL, ALTER COLUMN search_tsv SET NOT NULL;

-- incremental refresh for a set of specialists (call from the app / outbox worker after writes)
CREATE OR REPLACE FUNCTION refresh_specialist_search(ids uuid[]) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  DELETE FROM specialist_search ss WHERE ss.specialist_id = ANY (ids)
     AND NOT EXISTS (SELECT 1 FROM specialist s WHERE s.id = ss.specialist_id AND s.status = 'active');
  INSERT INTO specialist_search SELECT * FROM v_specialist_search_src v WHERE v.specialist_id = ANY (ids)
  ON CONFLICT (specialist_id) DO UPDATE SET
    city_id = EXCLUDED.city_id, district_id = EXCLUDED.district_id, location = EXCLUDED.location, travels = EXCLUDED.travels,
    travel_radius_m = EXCLUDED.travel_radius_m, languages = EXCLUDED.languages, category_ids = EXCLUDED.category_ids,
    leaf_ids = EXCLUDED.leaf_ids, price_min_rsd = EXCLUDED.price_min_rsd, price_max_rsd = EXCLUDED.price_max_rsd,
    rating = EXCLUDED.rating, reviews_count = EXCLUDED.reviews_count, score = EXCLUDED.score, available_on = EXCLUDED.available_on,
    display_name = EXCLUDED.display_name, search_tsv = EXCLUDED.search_tsv, search_tsv_own = EXCLUDED.search_tsv_own,
    refreshed_at = EXCLUDED.refreshed_at;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;
\timing off

VACUUM ANALYZE specialist_search;
SELECT count(*) AS rows, pg_size_pretty(pg_table_size('specialist_search')) AS table_size,
       round(avg(cardinality(category_ids)), 2) AS avg_category_ids, round(avg(length(search_tsv)), 1) AS avg_lexemes,
       round(avg(length(search_tsv_own)), 1) AS avg_lexemes_own, round(avg(pg_column_size(search_tsv))) AS avg_tsv_bytes
FROM specialist_search;
SELECT specialist_id, display_name, category_ids, leaf_ids, price_min_rsd, price_max_rsd, score, left(search_tsv::text, 300) AS tsv_head
FROM specialist_search ORDER BY specialist_id LIMIT 2;

\echo '== incremental refresh timings (1, 100, 1000 specialists)'
\timing on
SELECT refresh_specialist_search(ARRAY(SELECT id FROM specialist ORDER BY id LIMIT 1));
SELECT refresh_specialist_search(ARRAY(SELECT id FROM specialist ORDER BY id OFFSET 1000 LIMIT 100));
SELECT refresh_specialist_search(ARRAY(SELECT id FROM specialist ORDER BY id OFFSET 5000 LIMIT 1000));
\timing off
