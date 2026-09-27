-- (a) read-model: popular leaf category (apartment_cleaning, 65) + Belgrade, ORDER BY score, page 1
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE category_ids @> '{65}' AND city_id = 1
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
