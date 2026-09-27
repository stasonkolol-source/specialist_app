-- (b) personal feed, optimized: expand the specialist's subscriptions to leaf category ids first,
--     then use the partial (category_id, created_at) index over open requests
SELECT specialist_id AS sid FROM mp.subscription WHERE is_active GROUP BY specialist_id HAVING count(*) >= 3 ORDER BY specialist_id LIMIT 1 \gset
EXPLAIN (ANALYZE, BUFFERS)
WITH subs AS MATERIALIZED (
  SELECT s.district_ids, s.area,
         ARRAY(SELECT c2.id FROM mp.category c1 JOIN mp.category c2 ON c2.path <@ c1.path
               WHERE c1.id = ANY (s.category_ids)) AS leaf_ids
  FROM mp.subscription s WHERE s.specialist_id = :'sid' AND s.is_active)
SELECT r.id, r.title, r.created_at
FROM mp.request r
WHERE r.status = 'open'
  AND r.category_id = ANY (ARRAY(SELECT DISTINCT unnest(leaf_ids) FROM subs))
  AND EXISTS (SELECT 1 FROM subs
              WHERE r.category_id = ANY (subs.leaf_ids)
                AND (r.district_id = ANY (subs.district_ids) OR ST_Covers(subs.area, r.location::geometry)))
ORDER BY r.created_at DESC, r.id DESC
LIMIT 20;
