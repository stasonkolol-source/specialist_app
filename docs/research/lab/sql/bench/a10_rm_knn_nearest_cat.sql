-- (a) read-model: 20 nearest plumbers (47), no radius bound (KNN index scan + filter)
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, round(ST_Distance(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography)) AS dist_m
FROM mp.specialist_search
WHERE category_ids @> '{47}'
ORDER BY location <-> ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography
LIMIT 20;
