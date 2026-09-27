-- (a) read-model: 10 districts of Belgrade + category subtree 'cleaning' (3), ORDER BY score
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search
WHERE district_id = ANY ('{1,2,3,4,5,6,7,8,9,10}') AND category_ids @> '{3}'
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
