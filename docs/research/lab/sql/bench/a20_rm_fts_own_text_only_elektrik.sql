-- (a) comparison: 'электрик' against own texts only (no taxonomy enrichment), Belgrade
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, ts_rank_cd(search_tsv_own, q, 32) AS rank
FROM mp.specialist_search, public.q_all('электрик') q
WHERE search_tsv_own @@ q AND city_id = 1
ORDER BY rank DESC, specialist_id DESC
LIMIT 20;
