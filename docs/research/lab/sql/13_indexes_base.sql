-- 13_indexes_base.sql — FK / lookup indexes every OLTP schema needs (not search-specific).
\set ON_ERROR_STOP 1
\timing on
SET search_path = mp, public;
SET maintenance_work_mem = '512MB';
CREATE INDEX IF NOT EXISTS specialist_category_cat_idx ON specialist_category (category_id, specialist_id);
CREATE INDEX IF NOT EXISTS service_specialist_idx      ON service (specialist_id);
CREATE INDEX IF NOT EXISTS service_cat_price_idx       ON service (category_id, price_rsd) WHERE is_active;
CREATE INDEX IF NOT EXISTS review_specialist_idx       ON review (specialist_id, created_at DESC);
CREATE INDEX IF NOT EXISTS request_client_idx          ON request (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS response_request_idx        ON response (request_id);
CREATE INDEX IF NOT EXISTS response_specialist_idx     ON response (specialist_id, created_at DESC);
CREATE INDEX IF NOT EXISTS subscription_specialist_idx ON subscription (specialist_id);
CREATE INDEX IF NOT EXISTS subscription_district_sub_idx ON subscription_district (subscription_id);
CREATE INDEX IF NOT EXISTS subscription_category_sub_idx ON subscription_category (subscription_id);
CREATE INDEX IF NOT EXISTS category_parent_idx         ON category (parent_id);
CREATE INDEX IF NOT EXISTS category_path_gist          ON category USING gist (path);
CREATE INDEX IF NOT EXISTS category_term_cat_idx       ON category_term (category_id);
CREATE INDEX IF NOT EXISTS district_city_idx           ON district (city_id);
\timing off
VACUUM ANALYZE;
