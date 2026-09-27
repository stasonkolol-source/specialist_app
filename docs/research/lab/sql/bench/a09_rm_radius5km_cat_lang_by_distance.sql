-- (a) read-model: within 5 km of a point in central Belgrade + category subtree 'cleaning.home_clean' (22) + speaks ru,
--     ORDER BY distance (KNN operator)
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, round(ST_Distance(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography)) AS dist_m
FROM mp.specialist_search
WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 5000) AND category_ids @> '{22}' AND languages && '{ru}'
ORDER BY location <-> ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography
LIMIT 20;
