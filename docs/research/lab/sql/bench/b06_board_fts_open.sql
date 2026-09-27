-- (b) board text search over open requests: 'сантехник' or 'vodoinstalater' (ru|sr interpretation), newest first
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title, created_at
FROM mp.request, public.q_all('сантехник or vodoinstalater') q
WHERE status = 'open' AND search_tsv @@ q
ORDER BY created_at DESC, id DESC
LIMIT 20;
