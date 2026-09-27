-- (a) read-model FTS: 'vodoinstalater' (Serbian Latin), whole country, ORDER BY rank
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, ts_rank_cd(search_tsv, q, 32) AS rank
FROM mp.specialist_search, public.q_all('vodoinstalater') q
WHERE search_tsv @@ q
ORDER BY rank DESC, specialist_id DESC
LIMIT 20;
