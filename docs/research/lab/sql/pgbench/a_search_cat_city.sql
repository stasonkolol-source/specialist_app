\set cat random(45, 104)
\set ci random(1, 100)
SELECT specialist_id, display_name, score FROM mp.specialist_search
WHERE category_ids @> ARRAY[:cat]::int[]
  AND city_id = (CASE WHEN :ci <= 55 THEN 1 WHEN :ci <= 75 THEN 2 WHEN :ci <= 85 THEN 3 ELSE 4 END)
ORDER BY score DESC, specialist_id DESC LIMIT 20;
