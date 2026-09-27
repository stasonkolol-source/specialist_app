-- 12_seed_data.sql — synthetic "one year after launch" dataset.
--   50k specialists, ~250k price-list items, 300k requests (20k open), ~450k responses,
--   ~150k reviews, ~78k subscriptions. Texts from templates in ru / sr-Latn / sr-Cyrl / en.
-- Deterministic: setseed() + no parallel workers.
\set ON_ERROR_STOP 1
\timing on
SET search_path = mp, public;
SET max_parallel_workers_per_gather = 0;
SET work_mem = '256MB';
SELECT setseed(0.42);

CREATE INDEX IF NOT EXISTS district_boundary_gist ON district USING gist (boundary);

-- ---------- generation helpers ----------
DROP TABLE IF EXISTS gen_const;
CREATE TEMP TABLE gen_const AS
SELECT
  (SELECT array_agg(id ORDER BY id, s) FROM category c, generate_series(1, greatest(1, round(c.popularity * 20)::int)) s
    WHERE c.depth = 3) AS leaf_slots,
  (SELECT array_agg(id ORDER BY id, s) FROM city c, generate_series(1, round(c.gen_weight * 100)::int) s) AS city_slots,
  ARRAY['Алексей','Дмитрий','Сергей','Андрей','Иван','Михаил','Никита','Артём','Павел','Максим',
        'Ольга','Анна','Мария','Екатерина','Наталья','Юлия','Ирина','Татьяна','Елена','Светлана'] AS ru_first,
  ARRAY['А.','Б.','В.','Г.','Д.','Е.','Ж.','З.','И.','К.','Л.','М.','Н.','О.','П.','Р.','С.','Т.','Ф.','Ш.'] AS ru_last,
  ARRAY['Marko','Nikola','Stefan','Miloš','Luka','Aleksandar','Nemanja','Đorđe','Dušan','Vladimir',
        'Jelena','Milica','Ana','Marija','Jovana','Ivana','Tijana','Katarina','Dragana','Snežana'] AS sr_first,
  ARRAY['J.','P.','M.','S.','N.','K.','Đ.','Ž.','Č.','D.','R.','T.','V.','B.','G.','L.','O.','I.','Z.','A.'] AS sr_last,
  ARRAY['Гарантия на все работы.','Работаю аккуратно, убираю за собой.','Возможна оплата картой.','Свои материалы и инструменты.',
        'Выезд в день обращения.','Бесплатная консультация по телефону.','Работаю без выходных.','Опыт работы в России и Сербии.'] AS ru_extra,
  ARRAY['Garancija na sve radove.','Brzo, kvalitetno i povoljno.','Moguće plaćanje karticom.','Sopstveni materijal i alat.',
        'Dolazak istog dana.','Besplatna procena radova.','Radim i vikendom.','Dugogodišnje iskustvo.'] AS sr_extra,
  ARRAY['Warranty on all work.','Fast and reliable.','Card payments accepted.','Own tools and materials.','Same-day visits.','Free estimate.'] AS en_extra,
  ARRAY['Квартира в новостройке, 2 этаж.','Нужно сделать на этой неделе.','Материалы есть.','Прошу назвать цену и сроки.',
        'Возможна оплата наличными или картой.','Желательно с опытом и отзывами.','Удобно вечером после 18:00.'] AS ru_detail,
  ARRAY['Stan u novogradnji, drugi sprat.','Potrebno ove nedelje.','Materijal imam.','Molim cenu i rok.',
        'Plaćanje gotovinom ili karticom.','Poželjno iskustvo i preporuke.','Odgovara mi posle 18h.'] AS sr_detail,
  ARRAY['Apartment in a new building.','Needed this week.','Please quote price and timing.','Card or cash.'] AS en_detail;

-- per (category, lang): name + synonyms as an array (synthetic leaves: name only)
DROP TABLE IF EXISTS gen_terms;
CREATE TEMP TABLE gen_terms AS
SELECT c.id AS category_id, l.lang,
       coalesce((SELECT array_agg(t.term ORDER BY t.id) FROM category_term t WHERE t.category_id = c.id AND t.lang = l.lang),
                ARRAY[c.name->>l.lang]) AS terms,
       c.name->>l.lang AS cname
FROM category c CROSS JOIN (VALUES ('ru'),('sr-Latn'),('sr-Cyrl'),('en')) l(lang)
WHERE c.depth = 3;
CREATE UNIQUE INDEX ON gen_terms(category_id, lang);
ANALYZE gen_terms;

DROP TABLE IF EXISTS gen_siblings;
CREATE TEMP TABLE gen_siblings AS
SELECT parent_id, array_agg(id ORDER BY id) AS leaf_ids FROM category WHERE depth = 3 GROUP BY parent_id;

-- ---------- specialists ----------
DROP TABLE IF EXISTS gen_spec;
CREATE TEMP TABLE gen_spec AS
SELECT n,
       uuidv7(-(interval '1 day' * (400 - n * 400.0 / 50000))) AS id,      -- created over ~400 days, time-ordered
       now() - interval '1 day' * (400 - n * 400.0 / 50000) AS created_at,
       (random() < 0.5) AS is_ru,
       random() AS r_lang, random() AS r_script, random() AS r_extra_lang,
       g.city_slots[1 + floor(random() * cardinality(g.city_slots))::int] AS city_id,
       g.leaf_slots[1 + floor(random() * cardinality(g.leaf_slots))::int] AS leaf1,
       (ARRAY[0,0,0,0,0,0,0,1,1,1,1,1,1,1,2,2,2,2,3,3])[1 + floor(random() * 20)::int] AS n_extra,
       random() AS r_dist, random() AS r_az, random() AS r_travel, random() AS r_avail,
       1 + floor(random() * 25)::int AS years,
       floor(random() * 20)::int AS i_first, floor(random() * 20)::int AS i_last,
       floor(random() * 8)::int AS i_extra, floor(random() * 6)::int AS i_extra_en
FROM generate_series(1, 50000) n, gen_const g;

INSERT INTO specialist(id, display_name, about, primary_lang, languages, city_id, location, travels, travel_radius_m,
                       available_on, status, created_at, updated_at)
SELECT s.id,
       CASE WHEN s.is_ru THEN g.ru_first[1 + s.i_first] || ' ' || g.ru_last[1 + s.i_last]
            WHEN s.r_script < 0.2 THEN public.lab_sr_lat2cyr(g.sr_first[1 + s.i_first] || ' ' || g.sr_last[1 + s.i_last])
            ELSE g.sr_first[1 + s.i_first] || ' ' || g.sr_last[1 + s.i_last] END,
       CASE WHEN s.is_ru THEN
              jsonb_build_object('ru', format('%s: %s. Опыт работы %s лет. Работаю в городе %s%s. %s',
                   tru.cname, array_to_string(tru.terms[1:3], ', '), s.years, c.name->>'ru',
                   CASE WHEN s.r_travel < 0.7 THEN ', выезд к клиенту' ELSE '' END, g.ru_extra[1 + s.i_extra]))
              || CASE WHEN s.r_extra_lang < 0.2 THEN
                   jsonb_build_object('sr-Latn', format('%s: %s. Iskustvo %s godina. %s', tsl.cname, array_to_string(tsl.terms[1:2], ', '), s.years, g.sr_extra[1 + s.i_extra]))
                 ELSE '{}'::jsonb END
            ELSE
              jsonb_build_object(CASE WHEN s.r_script < 0.2 THEN 'sr-Cyrl' ELSE 'sr-Latn' END,
                 CASE WHEN s.r_script < 0.2 THEN public.lab_sr_lat2cyr(x.sr_text) ELSE x.sr_text END)
              || CASE WHEN s.r_extra_lang < 0.1 THEN
                   jsonb_build_object('en', format('%s: %s. %s years of experience. %s', ten.cname, array_to_string(ten.terms[1:2], ', '), s.years, g.en_extra[1 + s.i_extra_en]))
                 ELSE '{}'::jsonb END
       END,
       CASE WHEN s.is_ru THEN 'ru' WHEN s.r_script < 0.2 THEN 'sr-Cyrl' ELSE 'sr-Latn' END,
       CASE WHEN s.is_ru THEN
              CASE WHEN s.r_lang < 0.45 THEN ARRAY['ru'] WHEN s.r_lang < 0.75 THEN ARRAY['ru','en'] WHEN s.r_lang < 0.90 THEN ARRAY['ru','sr']
                   WHEN s.r_lang < 0.97 THEN ARRAY['ru','sr','en'] ELSE ARRAY['ru','uk'] END
            ELSE
              CASE WHEN s.r_lang < 0.45 THEN ARRAY['sr'] WHEN s.r_lang < 0.80 THEN ARRAY['sr','en'] WHEN s.r_lang < 0.92 THEN ARRAY['sr','ru']
                   WHEN s.r_lang < 0.97 THEN ARRAY['sr','en','ru'] ELSE ARRAY['sr','de'] END
       END,
       s.city_id,
       ST_Project(c.center, c.gen_radius_m * power(s.r_dist, 0.7), radians(s.r_az * 360)),
       s.r_travel < 0.7,
       CASE WHEN s.r_travel < 0.7 THEN (ARRAY[5000,10000,15000,20000,30000])[1 + floor(s.r_travel / 0.7 * 5)::int] END,
       CASE WHEN s.r_avail < 0.30 THEN current_date WHEN s.r_avail < 0.60 THEN current_date + (1 + floor(s.r_avail * 10))::int
            WHEN s.r_avail < 0.80 THEN current_date - (1 + floor(s.r_avail * 30))::int END,
       CASE WHEN s.r_avail > 0.985 THEN 'hidden' ELSE 'active' END,
       s.created_at, s.created_at
FROM gen_spec s CROSS JOIN gen_const g
JOIN city c ON c.id = s.city_id
JOIN gen_terms tru ON tru.category_id = s.leaf1 AND tru.lang = 'ru'
JOIN gen_terms tsl ON tsl.category_id = s.leaf1 AND tsl.lang = 'sr-Latn'
JOIN gen_terms ten ON ten.category_id = s.leaf1 AND ten.lang = 'en'
CROSS JOIN LATERAL (SELECT format('%s: %s. Iskustvo %s godina. Radim u gradu %s%s. %s',
                     tsl.cname, array_to_string(tsl.terms[1:3], ', '), s.years, c.name->>'sr-Latn',
                     CASE WHEN s.r_travel < 0.7 THEN ', dolazak na adresu' ELSE '' END, g.sr_extra[1 + s.i_extra]) AS sr_text) x;

-- specialist categories: primary leaf + 0..3 siblings
INSERT INTO specialist_category(specialist_id, category_id)
SELECT DISTINCT s.id, x.cat
FROM gen_spec s
JOIN category l ON l.id = s.leaf1
JOIN gen_siblings sb ON sb.parent_id = l.parent_id
CROSS JOIN LATERAL (
  SELECT s.leaf1 AS cat
  UNION ALL
  SELECT sb.leaf_ids[1 + floor(random() * cardinality(sb.leaf_ids))::int] FROM generate_series(1, s.n_extra)
) x;

-- ---------- price list: 3..7 services per specialist ----------
INSERT INTO service(id, specialist_id, category_id, title, lang, price_rsd, price_to_rsd, unit, is_active, created_at)
SELECT uuidv7(), sc.specialist_id, sc.category_id,
       t.terms[1 + floor(random() * cardinality(t.terms))::int] ||
         (CASE WHEN sp.primary_lang = 'ru' THEN (ARRAY['',' (срочно)',' — выезд',', стандарт',', сложный случай'])
               WHEN sp.primary_lang = 'sr-Cyrl' THEN (ARRAY['',' (хитно)',' — долазак',', стандард',', сложен случај'])
               ELSE (ARRAY['',' (hitno)',' — dolazak',', standard',', složen slučaj']) END)[1 + floor(random() * 5)::int],
       sp.primary_lang,
       greatest(300, round((c.price_base * (0.5 + random() * 1.3))::numeric, -2))::int,
       CASE WHEN random() < 0.3 THEN round((c.price_base * (1.8 + random()))::numeric, -2)::int END,
       (ARRAY['job','job','job','hour','visit'])[1 + floor(random() * 5)::int],
       random() < 0.95,
       sp.created_at + interval '1 day' * random() * 10
FROM (SELECT sc.*, row_number() OVER (PARTITION BY sc.specialist_id ORDER BY sc.category_id) AS k,
             count(*) OVER (PARTITION BY sc.specialist_id) AS n_cat
      FROM specialist_category sc) sc
JOIN specialist sp ON sp.id = sc.specialist_id
JOIN category c ON c.id = sc.category_id
JOIN gen_terms t ON t.category_id = sc.category_id AND t.lang = sp.primary_lang
CROSS JOIN LATERAL generate_series(1, ceil((3 + floor(random() * 5)) / sc.n_cat::numeric)::int) rep;

-- ---------- reviews: ~150k, skewed towards a subset of specialists ----------
-- (random picks are materialized first: a volatile expression inside a join condition would be
--  re-evaluated per row pair, and an uncorrelated sub-select with random() runs only once)
DROP TABLE IF EXISTS gen_review_pick;
CREATE TEMP TABLE gen_review_pick AS SELECT 1 + floor(power(random(), 2.2) * 50000)::int AS n FROM generate_series(1, 150000);
INSERT INTO review(id, specialist_id, author_id, rating, body, lang, created_at)
SELECT uuidv7(), s.id, gen_random_uuid(),
       (ARRAY[5,5,5,5,5,5,5,5,5,5,5,4,4,4,4,4,3,3,2,1])[1 + floor(random() * 20)::int],
       CASE WHEN s.is_ru THEN (ARRAY['Отличная работа, рекомендую!','Всё сделал быстро и аккуратно.','Нормально, но опоздал.','Цена соответствует качеству.'])[1 + floor(random() * 4)::int]
            ELSE (ARRAY['Odlično, preporučujem!','Sve urađeno brzo i uredno.','Solidno, ali kasnio.','Cena u skladu sa kvalitetom.'])[1 + floor(random() * 4)::int] END,
       CASE WHEN s.is_ru THEN 'ru' ELSE 'sr-Latn' END,
       now() - interval '1 day' * random() * 360
FROM gen_review_pick r
JOIN gen_spec s ON s.n = r.n;

UPDATE specialist sp SET rating = a.avg_rating, reviews_count = a.cnt
FROM (SELECT specialist_id, round(avg(rating), 2) AS avg_rating, count(*) AS cnt FROM review GROUP BY 1) a
WHERE a.specialist_id = sp.id;

-- ---------- requests: 20k open (last 21 days) + 280k history (last ~365 days) ----------
DROP TABLE IF EXISTS gen_req;
CREATE TEMP TABLE gen_req AS
SELECT n,
       CASE WHEN n <= 20000 THEN now() - interval '1 day' * random() * 21
            ELSE now() - interval '1 day' * (21 + power(random(), 1.3) * 344) END AS created_at,
       CASE WHEN n <= 20000 THEN 'open'
            ELSE (ARRAY['done','done','done','done','done','done','done','done','done',
                        'cancelled','cancelled','cancelled','expired','expired','expired','expired','expired','expired',
                        'in_progress','in_progress'])[1 + floor(random() * 20)::int] END AS status,
       g.leaf_slots[1 + floor(random() * cardinality(g.leaf_slots))::int] AS category_id,
       g.city_slots[1 + floor(random() * cardinality(g.city_slots))::int] AS city_id,
       random() AS r_lang, random() AS r_dist, random() AS r_az, random() AS r_budget, random() AS r_tpl,
       floor(random() * 7)::int AS i_detail
FROM generate_series(1, 300000) n, gen_const g;

INSERT INTO request(id, client_id, category_id, tag_ids, title, description, lang, urgency, budget_min_rsd, budget_max_rsd,
                    city_id, location, status, created_at, expires_at)
SELECT uuidv7(r.created_at - now()), gen_random_uuid(), r.category_id,
       (SELECT coalesce(array_agg(DISTINCT (1 + floor(random() * 20))::smallint), '{}') FROM generate_series(1, floor(random() * 4)::int + r.n * 0)),
       CASE WHEN r.r_lang < 0.45 THEN (ARRAY['Нужен специалист: ','Ищу: ','Срочно: ','Требуется: '])[1 + floor(r.r_tpl * 4)::int] || lower(tru.cname)
            WHEN r.r_lang < 0.85 THEN (ARRAY['Potreban majstor: ','Tražim: ','Hitno: ','Potrebno: '])[1 + floor(r.r_tpl * 4)::int] || lower(tsl.cname)
            WHEN r.r_lang < 0.95 THEN public.lab_sr_lat2cyr((ARRAY['Potreban majstor: ','Tražim: ','Hitno: ','Potrebno: '])[1 + floor(r.r_tpl * 4)::int] || lower(tsl.cname))
            ELSE (ARRAY['Need: ','Looking for: ','Urgent: ','Wanted: '])[1 + floor(r.r_tpl * 4)::int] || lower(ten.cname) END,
       CASE WHEN r.r_lang < 0.45 THEN tru.terms[1 + floor(random() * cardinality(tru.terms))::int] || '. ' || g.ru_detail[1 + r.i_detail] || ' ' || g.ru_detail[1 + (r.i_detail + 3) % 7]
            WHEN r.r_lang < 0.85 THEN tsl.terms[1 + floor(random() * cardinality(tsl.terms))::int] || '. ' || g.sr_detail[1 + r.i_detail] || ' ' || g.sr_detail[1 + (r.i_detail + 3) % 7]
            WHEN r.r_lang < 0.95 THEN public.lab_sr_lat2cyr(tsl.terms[1 + floor(random() * cardinality(tsl.terms))::int] || '. ' || g.sr_detail[1 + r.i_detail])
            ELSE ten.terms[1] || '. ' || g.en_detail[1 + r.i_detail % 4] END,
       CASE WHEN r.r_lang < 0.45 THEN 'ru' WHEN r.r_lang < 0.85 THEN 'sr-Latn' WHEN r.r_lang < 0.95 THEN 'sr-Cyrl' ELSE 'en' END,
       (ARRAY[0,0,0,1,1,1,1,1,2,2,2,2,2,2,2,3,3,3,3,3])[1 + floor(random() * 20)::int],
       CASE WHEN r.r_budget < 0.6 THEN round((c.price_base * (0.5 + r.r_budget))::numeric, -2)::int END,
       CASE WHEN r.r_budget < 0.6 THEN round((c.price_base * (0.5 + r.r_budget) * (1.2 + random() * 0.8))::numeric, -2)::int END,
       r.city_id,
       ST_Project(ci.center, ci.gen_radius_m * power(r.r_dist, 0.7), radians(r.r_az * 360)),
       r.status, r.created_at, r.created_at + interval '30 days'
FROM gen_req r CROSS JOIN gen_const g
JOIN category c ON c.id = r.category_id
JOIN city ci ON ci.id = r.city_id
JOIN gen_terms tru ON tru.category_id = r.category_id AND tru.lang = 'ru'
JOIN gen_terms tsl ON tsl.category_id = r.category_id AND tsl.lang = 'sr-Latn'
JOIN gen_terms ten ON ten.category_id = r.category_id AND ten.lang = 'en';

-- ---------- district assignment by point-in-polygon ----------
UPDATE specialist s SET district_id = d.id FROM district d WHERE ST_Covers(d.boundary, s.location::geometry);
UPDATE request r SET district_id = d.id FROM district d WHERE ST_Covers(d.boundary, r.location::geometry);

-- ---------- responses: 0..3 per request ----------
DROP TABLE IF EXISTS gen_resp;
CREATE TEMP TABLE gen_resp AS SELECT r.id AS request_id, floor(random() * 4)::int AS n_resp FROM request r;
DROP TABLE IF EXISTS gen_resp_pick;
CREATE TEMP TABLE gen_resp_pick AS
SELECT g.request_id, k, 1 + floor(random() * 50000)::int AS spec_n, random() AS r_t
FROM gen_resp g CROSS JOIN LATERAL generate_series(1, g.n_resp) k;

INSERT INTO response(id, request_id, specialist_id, message, price_rsd, status, created_at)
SELECT uuidv7(), r.id, s.id,
       CASE WHEN r.lang = 'ru' THEN 'Здравствуйте! Могу помочь, опыт большой.' ELSE 'Zdravo! Mogu da pomognem.' END,
       coalesce(r.budget_min_rsd, 3000),
       CASE WHEN r.status = 'done' AND p.k = 1 THEN 'accepted' WHEN r.status = 'open' THEN 'sent' ELSE 'rejected' END,
       r.created_at + interval '1 hour' * (1 + p.k * p.r_t * 24)
FROM gen_resp_pick p
JOIN request r ON r.id = p.request_id
JOIN gen_spec s ON s.n = p.spec_n;

-- ---------- subscriptions (~60% of specialists, 1..4 each) ----------
DROP TABLE IF EXISTS gen_sub;
CREATE TEMP TABLE gen_sub AS
SELECT sp.id AS specialist_id, sp.city_id, sp.location, k, random() AS r_kind, random() AS r_parent, random() AS r_radius, random() AS r_budget
FROM (SELECT sp.*, CASE WHEN random() < 0.6 THEN 1 + floor(random() * 4)::int ELSE 0 END AS n_sub
      FROM specialist sp WHERE sp.status = 'active') sp
CROSS JOIN LATERAL generate_series(1, sp.n_sub) k;

INSERT INTO subscription(id, specialist_id, category_ids, district_ids, center, radius_m, area, min_budget_rsd, created_at)
SELECT uuidv7(), g.specialist_id,
       CASE WHEN g.r_parent < 0.25   -- subscribe to the whole parent group of one of own categories
            THEN (SELECT ARRAY[min(c.parent_id)] FROM specialist_category sc JOIN category c ON c.id = sc.category_id WHERE sc.specialist_id = g.specialist_id)
            ELSE (SELECT array_agg(sc.category_id ORDER BY sc.category_id) FROM specialist_category sc WHERE sc.specialist_id = g.specialist_id) END,
       CASE WHEN g.r_kind < 0.6 THEN
         (SELECT array_agg(d.id ORDER BY d.id) FROM (
            SELECT d.id FROM district d WHERE d.city_id = g.city_id
            ORDER BY d.center <-> g.location LIMIT 1 + floor(g.r_radius * 10)::int) d) END,
       CASE WHEN g.r_kind >= 0.6 THEN g.location END,
       CASE WHEN g.r_kind >= 0.6 THEN (ARRAY[2000,3000,5000,8000,10000,15000,25000])[1 + floor(g.r_radius * 7)::int] END,
       CASE WHEN g.r_kind >= 0.6 THEN ST_Buffer(g.location, (ARRAY[2000,3000,5000,8000,10000,15000,25000])[1 + floor(g.r_radius * 7)::int], 'quad_segs=8')::geometry END,
       CASE WHEN g.r_budget < 0.3 THEN (ARRAY[2000,5000,10000])[1 + floor(g.r_budget / 0.3 * 3)::int] END,
       now() - interval '1 day' * random() * 300
FROM gen_sub g;

INSERT INTO subscription_category(subscription_id, category_id)
SELECT id, unnest(category_ids) FROM subscription ON CONFLICT DO NOTHING;
INSERT INTO subscription_district(subscription_id, district_id)
SELECT id, unnest(district_ids) FROM subscription WHERE district_ids IS NOT NULL ON CONFLICT DO NOTHING;

\timing off
SELECT 'specialist' t, count(*) FROM specialist UNION ALL SELECT 'specialist_category', count(*) FROM specialist_category
UNION ALL SELECT 'service', count(*) FROM service UNION ALL SELECT 'review', count(*) FROM review
UNION ALL SELECT 'request', count(*) FROM request UNION ALL SELECT 'request_open', count(*) FROM request WHERE status = 'open'
UNION ALL SELECT 'response', count(*) FROM response UNION ALL SELECT 'subscription', count(*) FROM subscription
UNION ALL SELECT 'subscription_category', count(*) FROM subscription_category UNION ALL SELECT 'subscription_district', count(*) FROM subscription_district
UNION ALL SELECT 'specialist_without_district', count(*) FROM specialist WHERE district_id IS NULL
UNION ALL SELECT 'request_without_district', count(*) FROM request WHERE district_id IS NULL;
