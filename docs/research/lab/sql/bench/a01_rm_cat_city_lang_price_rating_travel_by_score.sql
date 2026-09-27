-- (a) read-model: category subtree 'repair.electric' (id 15) + Belgrade + speaks ru + price overlap 1000..5000
--     + rating>=4 + travels; ORDER BY score, first page
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score, price_min_rsd
FROM mp.specialist_search
WHERE category_ids @> '{15}' AND city_id = 1 AND languages && '{ru}'
  AND price_min_rsd <= 5000 AND price_max_rsd >= 1000 AND rating >= 4.0 AND travels
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
