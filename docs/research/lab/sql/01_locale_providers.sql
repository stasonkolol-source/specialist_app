-- 01_locale_providers.sql — does the database locale provider affect Cyrillic handling in
-- lower()/upper(), regex classes, pg_trgm and the FTS parser?
-- Databases compared (all UTF8):
--   lab          : builtin provider, C.UTF-8   (cluster default of this lab)
--   t_libc_c     : libc provider,   LC_COLLATE=LC_CTYPE=C  (a common "fast" default)
--   t_libc_en    : libc provider,   en_US.utf8
--   t_icu_und    : icu provider,    ICU root locale 'und' (LC_CTYPE=C)
--   t_builtin_cctype : builtin C.UTF-8 but LC_COLLATE=LC_CTYPE=C
--   t_libc_cutf8 : libc provider,   C.UTF-8 (glibc)
\pset pager off
\set ON_ERROR_STOP 1
SELECT 'CREATE DATABASE t_libc_c TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER libc LOCALE ''C'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 't_libc_c') \gexec
SELECT 'CREATE DATABASE t_libc_en TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER libc LOCALE ''en_US.utf8'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 't_libc_en') \gexec
SELECT 'CREATE DATABASE t_icu_und TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER icu ICU_LOCALE ''und'' LOCALE ''C'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 't_icu_und') \gexec

SELECT 'CREATE DATABASE t_builtin_cctype TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER builtin BUILTIN_LOCALE ''C.UTF-8'' LC_COLLATE ''C'' LC_CTYPE ''C'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 't_builtin_cctype') \gexec
SELECT 'CREATE DATABASE t_libc_cutf8 TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER libc LOCALE ''C.UTF-8'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 't_libc_cutf8') \gexec

SELECT datname, datlocprovider AS prov, datcollate, datctype, datlocale
FROM pg_database WHERE datname IN ('lab','t_libc_c','t_libc_en','t_icu_und','t_builtin_cctype','t_libc_cutf8') ORDER BY 1;

\set checks 'CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;'

\connect lab
\i /lab/scripts/locale_checks.psql
\connect t_libc_c
:checks
\i /lab/scripts/locale_checks.psql
\connect t_libc_en
:checks
\i /lab/scripts/locale_checks.psql
\connect t_icu_und
:checks
\i /lab/scripts/locale_checks.psql
\connect t_builtin_cctype
:checks
\i /lab/scripts/locale_checks.psql
\connect t_libc_cutf8
:checks
\i /lab/scripts/locale_checks.psql
