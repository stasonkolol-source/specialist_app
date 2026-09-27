\set cat random(45, 104)
\set dx random(-400, 400)
\set dy random(-300, 300)
INSERT INTO mp.request(client_id, category_id, title, description, lang, urgency, city_id, location, status, created_at, expires_at)
VALUES (gen_random_uuid(), :cat, 'Bench request: popravka', 'bench', 'sr-Latn', 1, 1,
        ST_SetSRID(ST_MakePoint(20.4612 + :dx / 10000.0, 44.8125 + :dy / 10000.0), 4326)::geography,
        'open', now(), now() + interval '30 days');
