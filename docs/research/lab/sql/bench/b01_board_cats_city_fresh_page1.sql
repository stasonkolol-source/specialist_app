-- (b) board: open requests in 5 categories (electric/plumbing/cleaning leaves) in Belgrade, newest first
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title, category_id, created_at
FROM mp.request
WHERE status = 'open' AND city_id = 1 AND category_id = ANY ('{45,46,47,48,65}')
ORDER BY created_at DESC, id DESC
LIMIT 20;
