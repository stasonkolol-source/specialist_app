-- (a) normalized equivalent of a03 via link table specialist_category (vs array + GIN in a03)
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.id, s.display_name, s.rating
FROM mp.specialist s
JOIN mp.specialist_category sc ON sc.specialist_id = s.id AND sc.category_id = 65
WHERE s.status = 'active' AND s.city_id = 1
ORDER BY s.rating DESC NULLS LAST, s.id DESC
LIMIT 20;
