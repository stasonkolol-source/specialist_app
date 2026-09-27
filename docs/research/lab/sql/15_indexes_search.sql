-- 15_indexes_search.sql — search / board / matching / autocomplete indexes (+ some alternatives to compare).
\set ON_ERROR_STOP 1
\timing on
SET search_path = mp, public;
SET maintenance_work_mem = '512MB';

-- ===== read-model (specialist_search)
CREATE INDEX ss_category_gin     ON specialist_search USING gin (category_ids);
CREATE INDEX ss_tsv_gin          ON specialist_search USING gin (search_tsv);
CREATE INDEX ss_tsv_own_gin      ON specialist_search USING gin (search_tsv_own);          -- comparison only
CREATE INDEX ss_location_gist    ON specialist_search USING gist (location);
CREATE INDEX ss_city_score_idx   ON specialist_search (city_id, score DESC, specialist_id DESC);
CREATE INDEX ss_district_idx     ON specialist_search (district_id);
CREATE INDEX ss_cat_city_gin     ON specialist_search USING gin (category_ids, city_id);    -- btree_gin multicolumn variant
CREATE INDEX ss_name_trgm        ON specialist_search USING gin (public.search_norm(display_name) gin_trgm_ops);

-- ===== normalized model (for the JOIN comparison)
CREATE INDEX specialist_city_rating_idx ON specialist (city_id, rating DESC NULLS LAST, id DESC) WHERE status = 'active';
CREATE INDEX specialist_location_gist   ON specialist USING gist (location) WHERE status = 'active';

-- ===== request board: partial indexes over open requests only (~20k of 300k)
ALTER TABLE request ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
  CASE lang WHEN 'ru' THEN public.tsv_ru(title || ' ' || coalesce(description, ''))
            WHEN 'en' THEN public.tsv_en(title || ' ' || coalesce(description, ''))
            ELSE public.tsv_sr(title || ' ' || coalesce(description, '')) END) STORED;
CREATE INDEX req_open_created_idx      ON request (created_at DESC, id DESC) WHERE status = 'open';
CREATE INDEX req_open_cat_created_idx  ON request (category_id, created_at DESC, id DESC) WHERE status = 'open';
CREATE INDEX req_open_city_created_idx ON request (city_id, created_at DESC, id DESC) WHERE status = 'open';
CREATE INDEX req_open_dist_created_idx ON request (district_id, created_at DESC, id DESC) WHERE status = 'open';
CREATE INDEX req_open_location_gist    ON request USING gist (location) WHERE status = 'open';
CREATE INDEX req_open_tsv_gin          ON request USING gin (search_tsv) WHERE status = 'open';
-- non-partial alternative, for size comparison
CREATE INDEX req_status_cat_created_idx ON request (status, category_id, created_at DESC, id DESC);

-- ===== subscriptions: variant A (arrays / geometry)
CREATE INDEX sub_category_gin ON subscription USING gin (category_ids) WHERE is_active;
CREATE INDEX sub_district_gin ON subscription USING gin (district_ids) WHERE is_active;
CREATE INDEX sub_area_gist    ON subscription USING gist (area) WHERE is_active AND area IS NOT NULL;
CREATE INDEX sub_center_gist  ON subscription USING gist (center) WHERE is_active AND center IS NOT NULL;  -- NULLs bloat GiST: 20 MB vs 2.1 MB (results/15b_gist_nulls.txt)
-- variant B: PKs of subscription_category(category_id, subscription_id) and subscription_district(district_id, subscription_id)

-- ===== autocomplete over taxonomy terms
CREATE INDEX term_norm_btree     ON category_term (term_norm);                       -- prefix LIKE with a C-collation column
CREATE INDEX term_norm_trgm_gin  ON category_term USING gin (term_norm gin_trgm_ops);
CREATE INDEX term_norm_trgm_gist ON category_term USING gist (term_norm gist_trgm_ops); -- KNN (<->) ordering
\timing off

VACUUM ANALYZE;

\echo '== sizes'
SELECT c.relname AS relation, c.relkind AS kind, pg_size_pretty(pg_relation_size(c.oid)) AS size, pg_relation_size(c.oid) AS bytes,
       i.indrelid::regclass AS table_
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_index i ON i.indexrelid = c.oid
WHERE n.nspname = 'mp' AND c.relkind IN ('r','i')
ORDER BY c.relkind DESC, pg_relation_size(c.oid) DESC;
SELECT pg_size_pretty(pg_database_size('lab')) AS database_size;
