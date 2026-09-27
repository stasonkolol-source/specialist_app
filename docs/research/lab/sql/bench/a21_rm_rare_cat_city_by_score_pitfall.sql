-- (a) pitfall check: RARE leaf category in the biggest city, ORDER BY score LIMIT 20.
--     The planner may walk (city_id, score) in order and filter category -> scans most of the city.
SELECT c.id AS rare_cat FROM mp.category c
WHERE c.depth = 3 AND c.is_synthetic
ORDER BY (SELECT count(*) FROM mp.specialist_search s WHERE s.city_id = 1 AND s.category_ids @> ARRAY[c.id]), c.id
LIMIT 1 \gset
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE category_ids @> ARRAY[:rare_cat]::int[] AND city_id = 1
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
