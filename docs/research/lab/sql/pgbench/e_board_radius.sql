\set root random(1, 14)
\set dx random(-400, 400)
\set dy random(-300, 300)
SELECT r.id, r.title, r.created_at FROM mp.request r
WHERE r.status = 'open'
  AND ST_DWithin(r.location, ST_SetSRID(ST_MakePoint(20.4612 + :dx / 10000.0, 44.8125 + :dy / 10000.0), 4326)::geography, 10000)
  AND r.category_id IN (SELECT c.id FROM mp.category c JOIN mp.category root ON root.id = :root AND c.path <@ root.path)
ORDER BY r.created_at DESC, r.id DESC LIMIT 20;
