-- (d) autocomplete: prefix 'элек' on normalized term (btree on a C.UTF-8 column supports LIKE 'x%')
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT ON (t.category_id) t.category_id, t.term, t.lang
FROM mp.category_term t
WHERE t.term_norm LIKE public.search_norm('элек') || '%'
ORDER BY t.category_id, t.weight DESC
LIMIT 10;
