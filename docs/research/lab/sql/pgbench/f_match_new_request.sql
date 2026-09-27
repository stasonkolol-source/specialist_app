\set cat random(45, 104)
\set d random(1, 52)
SELECT DISTINCT s.specialist_id
FROM mp.subscription s, mp.category c, mp.district d
WHERE c.id = :cat AND d.id = :d AND s.is_active
  AND s.category_ids && ARRAY(SELECT a.id FROM mp.category a WHERE a.path @> c.path)
  AND (s.district_ids && ARRAY[:d]::int[] OR ST_Intersects(s.area, d.center::geometry));
