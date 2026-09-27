\set cat random(45, 102)
\set ci random(1, 100)
SELECT id, title, created_at FROM mp.request
WHERE status = 'open' AND city_id = (CASE WHEN :ci <= 55 THEN 1 WHEN :ci <= 75 THEN 2 WHEN :ci <= 85 THEN 3 ELSE 4 END)
  AND category_id = ANY (ARRAY[:cat, :cat + 1, :cat + 2]::int[])
ORDER BY created_at DESC, id DESC LIMIT 20;
