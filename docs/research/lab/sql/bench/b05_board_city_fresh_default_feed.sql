-- (b) board default feed: all open requests in Belgrade, newest first
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title, category_id, created_at
FROM mp.request
WHERE status = 'open' AND city_id = 1
ORDER BY created_at DESC, id DESC
LIMIT 20;
