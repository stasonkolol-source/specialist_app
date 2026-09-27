-- (c) matching for a new request (category 65 apartment_cleaning -> itself + ancestors {3,22,65}; district 1; point; budget 5000):
--     variant A: arrays + GIN, district OR circle-polygon in one predicate
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT s.specialist_id
FROM mp.subscription s
WHERE s.is_active AND s.category_ids && '{3,22,65}'::int[]
  AND (s.district_ids && '{1}'::int[] OR ST_Intersects(s.area, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326)))
  AND (s.min_budget_rsd IS NULL OR s.min_budget_rsd <= 5000);
