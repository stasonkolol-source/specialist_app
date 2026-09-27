-- (a) normalized JOIN/EXISTS equivalent of a01 (category subtree via ltree, price via services)
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.id, s.display_name, s.rating
FROM mp.specialist s
WHERE s.status = 'active' AND s.city_id = 1 AND s.languages && '{ru}' AND s.rating >= 4.0 AND s.travels
  AND EXISTS (SELECT 1 FROM mp.specialist_category sc JOIN mp.category c ON c.id = sc.category_id
              WHERE sc.specialist_id = s.id AND c.path <@ 'repair.electric')
  AND EXISTS (SELECT 1 FROM mp.service sv WHERE sv.specialist_id = s.id AND sv.is_active
              AND sv.price_rsd BETWEEN 1000 AND 5000)
ORDER BY s.rating DESC NULLS LAST, s.id DESC
LIMIT 20;
