-- (c) variant B: link tables subscription_category / subscription_district
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT s.specialist_id
FROM mp.subscription_category sc
JOIN mp.subscription s ON s.id = sc.subscription_id
WHERE sc.category_id IN (3, 22, 65) AND s.is_active
  AND (s.min_budget_rsd IS NULL OR s.min_budget_rsd <= 5000)
  AND (EXISTS (SELECT 1 FROM mp.subscription_district sd WHERE sd.subscription_id = s.id AND sd.district_id = 1)
       OR ST_Intersects(s.area, ST_SetSRID(ST_MakePoint(20.4682, 44.7974), 4326)));
