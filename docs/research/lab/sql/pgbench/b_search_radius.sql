\set sub random(15, 44)
\set dx random(-400, 400)
\set dy random(-300, 300)
SELECT specialist_id, display_name FROM mp.specialist_search
WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612 + :dx / 10000.0, 44.8125 + :dy / 10000.0), 4326)::geography, 5000)
  AND category_ids @> ARRAY[:sub]::int[]
ORDER BY location <-> ST_SetSRID(ST_MakePoint(20.4612 + :dx / 10000.0, 44.8125 + :dy / 10000.0), 4326)::geography
LIMIT 20;
