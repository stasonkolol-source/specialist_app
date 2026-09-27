-- (d) typo 'manikur' -> KNN by trigram distance (GiST <->), always returns top-10
EXPLAIN (ANALYZE, BUFFERS)
SELECT t.category_id, t.term, t.term_norm <-> public.search_norm('manikur') AS dist
FROM mp.category_term t
ORDER BY t.term_norm <-> public.search_norm('manikur')
LIMIT 10;
