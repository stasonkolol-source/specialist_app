-- (a) read-model FTS: 'ремонт стиральной машины' in Belgrade, ORDER BY rank
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, ts_rank_cd(search_tsv, q, 32) AS rank
FROM mp.specialist_search, public.q_all('ремонт стиральной машины') q
WHERE search_tsv @@ q AND city_id = 1
ORDER BY rank DESC, specialist_id DESC
LIMIT 20;
