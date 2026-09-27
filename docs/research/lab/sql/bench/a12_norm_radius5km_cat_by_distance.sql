-- (a) normalized equivalent of a09
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.id, s.display_name, round(ST_Distance(s.location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography)) AS dist_m
FROM mp.specialist s
WHERE s.status = 'active' AND ST_DWithin(s.location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 5000) AND s.languages && '{ru}'
  AND EXISTS (SELECT 1 FROM mp.specialist_category sc JOIN mp.category c ON c.id = sc.category_id
              WHERE sc.specialist_id = s.id AND c.path <@ 'cleaning.home_clean')
ORDER BY s.location <-> ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography
LIMIT 20;
