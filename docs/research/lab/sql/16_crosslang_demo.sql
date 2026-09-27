-- 16_crosslang_demo.sql — recall/precision of three ways to answer a query on the real lab dataset:
--   own-text FTS (search_tsv_own), FTS over the taxonomy-enriched document (search_tsv),
--   and taxonomy lookup "term -> category_id" (exact on the normalized key, or fuzzy top-1 via trigram KNN).
-- Ground truth = specialists that have the expected leaf category.
\pset pager off
SET search_path = mp, public;
SET max_parallel_workers_per_gather = 0;

WITH q(query, expected_cat) AS (VALUES
  ('электрик', 45), ('električar', 45), ('електричар', 45), ('elektricar', 45),
  ('сантехник', 47), ('vodoinstalater', 47), ('водоинсталатер', 47),
  ('маляр', 49), ('moler', 49),
  ('стиралка', 58), ('veš mašina', 58), ('ремонт стиральной машины', 58),
  ('маникюр', 74), ('manikir', 74), ('переезд', 70), ('selidbe', 70),
  ('электирк', 45), ('vodoinstaler', 47), ('manikur', 74))
SELECT q.query,
  (SELECT count(*) FROM specialist_search WHERE leaf_ids @> ARRAY[q.expected_cat]) AS relevant,
  (SELECT count(*) FROM specialist_search WHERE search_tsv_own @@ public.q_all(q.query)) AS own_found,
  (SELECT count(*) FROM specialist_search WHERE search_tsv_own @@ public.q_all(q.query) AND leaf_ids @> ARRAY[q.expected_cat]) AS own_hits,
  (SELECT count(*) FROM specialist_search WHERE search_tsv @@ public.q_all(q.query)) AS enriched_found,
  (SELECT count(*) FROM specialist_search WHERE search_tsv @@ public.q_all(q.query) AND leaf_ids @> ARRAY[q.expected_cat]) AS enriched_hits,
  (SELECT count(*) FROM specialist_search
    WHERE category_ids && ARRAY(SELECT DISTINCT category_id FROM category_term WHERE term_norm = public.search_norm(q.query))) AS taxo_exact_found,
  (SELECT string_agg(DISTINCT c.slug, ',') FROM category_term t JOIN category c ON c.id = t.category_id
    WHERE t.category_id = (SELECT category_id FROM category_term ORDER BY term_norm <-> public.search_norm(q.query) LIMIT 1)) AS taxo_fuzzy_top1
FROM q;

\echo '-- recall = hits / relevant; precision = hits / found (computed in the report from the table above)'
