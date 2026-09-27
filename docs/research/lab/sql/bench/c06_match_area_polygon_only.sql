-- (c) circle materialized as polygon (area) + GiST: point-in-area
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT s.specialist_id
FROM mp.subscription s
WHERE s.is_active AND s.area IS NOT NULL AND s.category_ids && '{3,22,65}'::int[]
  AND ST_Intersects(s.area, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326));
