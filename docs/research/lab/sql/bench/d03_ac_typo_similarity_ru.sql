-- (d) typo 'электирк' -> trigram similarity (% operator, GIN trgm)
EXPLAIN (ANALYZE, BUFFERS)
SELECT t.category_id, t.term, similarity(t.term_norm, public.search_norm('электирк')) AS sim
FROM mp.category_term t
WHERE t.term_norm % public.search_norm('электирк')
ORDER BY sim DESC
LIMIT 10;
