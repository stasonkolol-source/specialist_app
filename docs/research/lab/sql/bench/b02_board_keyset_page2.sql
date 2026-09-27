-- (b) board keyset page 2 of b01
SELECT created_at AS c_ts, id AS c_id FROM mp.request
WHERE status = 'open' AND city_id = 1 AND category_id = ANY ('{45,46,47,48,65}')
ORDER BY created_at DESC, id DESC OFFSET 19 LIMIT 1 \gset
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title, category_id, created_at
FROM mp.request
WHERE status = 'open' AND city_id = 1 AND category_id = ANY ('{45,46,47,48,65}')
  AND (created_at, id) < (:'c_ts'::timestamptz, :'c_id'::uuid)
ORDER BY created_at DESC, id DESC
LIMIT 20;
