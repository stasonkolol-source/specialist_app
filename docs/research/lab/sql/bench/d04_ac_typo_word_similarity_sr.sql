-- (d) typo 'vodoinstaler' -> word_similarity (<% operator) handles a word inside a longer term
EXPLAIN (ANALYZE, BUFFERS)
SELECT t.category_id, t.term, word_similarity(public.search_norm('vodoinstaler'), t.term_norm) AS wsim
FROM mp.category_term t
WHERE public.search_norm('vodoinstaler') <% t.term_norm
ORDER BY wsim DESC
LIMIT 10;
