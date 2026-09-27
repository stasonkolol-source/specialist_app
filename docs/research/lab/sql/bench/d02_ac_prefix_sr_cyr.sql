-- (d) autocomplete: Serbian Cyrillic prefix 'водоин' matches Latin/Cyrillic/typed-without-diacritics terms
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT ON (t.category_id) t.category_id, t.term, t.lang
FROM mp.category_term t
WHERE t.term_norm LIKE public.search_norm('водоин') || '%'
ORDER BY t.category_id, t.weight DESC
LIMIT 10;
