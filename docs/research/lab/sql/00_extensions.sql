-- 00_extensions.sql — which extensions are available/installable, their versions,
-- built-in UUID generators (PG18 uuidv7) and preload-dependent extensions.
\pset pager off
\echo '== server'
SELECT version();
SHOW shared_preload_libraries;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
-- optional, installed from PGDG in the lab image (EXTRA_EXTENSIONS="pgvector cron")
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_cron;   -- requires shared_preload_libraries=pg_cron + cron.database_name

\echo '== installed extensions'
SELECT extname, extversion FROM pg_extension ORDER BY extname;

\echo '== PostGIS build details'
SELECT postgis_full_version();

\echo '== UUID generators'
SELECT uuidv7() AS v7_a, uuidv7() AS v7_b, gen_random_uuid() AS v4;
-- uuidv7 embeds a millisecond timestamp -> monotonic within a backend, index-friendly (append-only b-tree)
SELECT uuid_extract_version(uuidv7()) AS ver, uuid_extract_timestamp(uuidv7()) AS ts;
-- time-shifted v7 (useful for backfills with historical created_at)
SELECT uuidv7(interval '-30 days') AS v7_30_days_ago;

\echo '== monotonicity check: 100k uuidv7 generated in one statement are strictly increasing'
SELECT count(*) FILTER (WHERE u <= prev) AS non_increasing
FROM (SELECT u, lag(u) OVER (ORDER BY n) AS prev
      FROM (SELECT n, uuidv7() AS u FROM generate_series(1, 100000) n) s) t;

\echo '== quick functional checks'
SELECT similarity('электрик', 'электирк') AS trgm_ru, levenshtein('vodoinstalater', 'vodoinstaler') AS lev,
       unaccent('čćšžđ ČĆŠŽĐ') AS unaccent_sr, 'Električar'::citext = 'ELEKTRIČAR'::citext AS citext_eq,
       'services.repair.electric'::ltree <@ 'services.repair'::ltree AS ltree_desc,
       '[1,2,3]'::vector <-> '[1,2,4]'::vector AS pgvector_l2;
SELECT cron.schedule('lab-noop', '*/10 * * * *', 'SELECT 1') AS cron_job_id;
SELECT jobid, schedule, command FROM cron.job;
SELECT cron.unschedule('lab-noop');

\echo '== available but not installed (selection)'
SELECT name, default_version FROM pg_available_extensions
WHERE name IN ('postgis_topology','postgis_raster','postgis_tiger_geocoder','address_standardizer','hstore',
               'intarray','dict_int','dict_xsyn','pg_prewarm','pg_buffercache','amcheck','pgstattuple','tsm_system_rows')
ORDER BY name;
