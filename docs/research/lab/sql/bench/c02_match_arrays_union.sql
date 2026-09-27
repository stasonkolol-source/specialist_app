-- (c) same as c01, rewritten as UNION of an index-friendly district branch and an area branch
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.specialist_id FROM mp.subscription s
WHERE s.is_active AND s.category_ids && '{3,22,65}'::int[] AND s.district_ids && '{1}'::int[]
  AND (s.min_budget_rsd IS NULL OR s.min_budget_rsd <= 5000)
UNION
SELECT s.specialist_id FROM mp.subscription s
WHERE s.is_active AND s.area IS NOT NULL AND s.category_ids && '{3,22,65}'::int[] AND ST_Intersects(s.area, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326))
  AND (s.min_budget_rsd IS NULL OR s.min_budget_rsd <= 5000);
