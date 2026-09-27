-- (b) board: open requests within 10 km, category subtree 'repair' (via ltree -> ids), urgency <= today, budget >= 3000
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id, r.title, r.created_at, round(ST_Distance(r.location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography)) AS dist_m
FROM mp.request r
WHERE r.status = 'open' AND ST_DWithin(r.location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 10000)
  AND r.category_id IN (SELECT id FROM mp.category WHERE path <@ 'repair')
  AND r.urgency <= 1 AND coalesce(r.budget_max_rsd, 0) >= 3000
ORDER BY r.created_at DESC, r.id DESC
LIMIT 20;
