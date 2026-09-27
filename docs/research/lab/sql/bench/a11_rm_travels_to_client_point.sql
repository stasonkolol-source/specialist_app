-- (a) read-model: specialists (electric subtree) whose own travel radius covers the client's point.
--     per-row radius is not indexable -> bound by the max radius (30 km) for the GiST index, then exact check
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE travels AND category_ids @> '{15}'
  AND ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 30000)
  AND ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, travel_radius_m)
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
