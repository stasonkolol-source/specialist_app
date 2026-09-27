-- (a) combined: text 'manikir' + category subtree beauty (5) + 7 km radius + rating >= 4.5, ORDER BY score
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, score
FROM mp.specialist_search, public.q_all('manikir') q
WHERE search_tsv @@ q AND category_ids @> '{5}' AND ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 7000) AND rating >= 4.5
ORDER BY score DESC, specialist_id DESC
LIMIT 20;
