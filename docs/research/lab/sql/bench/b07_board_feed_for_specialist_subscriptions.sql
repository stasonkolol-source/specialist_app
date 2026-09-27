-- (b) personal feed: open requests matching ANY active subscription of one specialist (categories incl. subtree + districts or circle)
SELECT specialist_id AS sid FROM mp.subscription WHERE is_active GROUP BY specialist_id HAVING count(*) >= 3 ORDER BY specialist_id LIMIT 1 \gset
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id, r.title, r.created_at
FROM mp.request r
WHERE r.status = 'open'
  AND EXISTS (
    SELECT 1 FROM mp.subscription s
    JOIN mp.category sc ON sc.id = ANY (s.category_ids)
    JOIN mp.category rc ON rc.id = r.category_id AND rc.path <@ sc.path
    WHERE s.specialist_id = :'sid' AND s.is_active
      AND (r.district_id = ANY (s.district_ids) OR ST_Covers(s.area, r.location::geometry)))
ORDER BY r.created_at DESC, r.id DESC
LIMIT 20;
