-- (a) keyset pagination, page 2 of a03 (cursor = last row of page 1)
SELECT score AS c_score, specialist_id AS c_id FROM mp.specialist_search
WHERE category_ids @> '{65}' AND city_id = 1 ORDER BY score DESC, specialist_id DESC OFFSET 19 LIMIT 1 \gset
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE category_ids @> '{65}' AND city_id = 1
  AND (score, specialist_id) < (:c_score::real, :'c_id'::uuid)
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
