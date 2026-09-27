-- (a) OFFSET pagination deep page (rows 1001..1020) of a broad listing (Belgrade, all categories), for comparison
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE city_id = 1
ORDER BY score DESC, specialist_id DESC
OFFSET 1000 LIMIT 20;
