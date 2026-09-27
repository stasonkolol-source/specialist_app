-- (b) board: open requests in 10 districts + category subtree 'cleaning', newest first
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id, r.title, r.created_at
FROM mp.request r
WHERE r.status = 'open' AND r.district_id = ANY ('{1,2,3,4,5,6,7,8,9,10}')
  AND r.category_id IN (SELECT id FROM mp.category WHERE path <@ 'cleaning')
ORDER BY r.created_at DESC, r.id DESC
LIMIT 20;
