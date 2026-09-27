-- (c) same, bounded by the max allowed radius (25 km) so the GiST index on center can be used, then exact per-row check
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT s.specialist_id
FROM mp.subscription s
WHERE s.is_active AND s.center IS NOT NULL AND s.category_ids && '{3,22,65}'::int[]
  AND ST_DWithin(s.center, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326)::geography, 25000)
  AND ST_DWithin(s.center, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326)::geography, s.radius_m);
