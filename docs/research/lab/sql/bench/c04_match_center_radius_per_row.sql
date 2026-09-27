-- (c) circle stored as center + radius_m: per-row radius in ST_DWithin (not index-assisted)
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT s.specialist_id
FROM mp.subscription s
WHERE s.is_active AND s.center IS NOT NULL AND s.category_ids && '{3,22,65}'::int[]
  AND ST_DWithin(s.center, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326)::geography, s.radius_m);
