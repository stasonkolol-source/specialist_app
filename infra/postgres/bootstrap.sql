-- Bootstrap базы: всё, что требует суперпользователя (DEVELOPMENT_PLAN 0.3, ADR-0005, ADR-0020 §4).
-- Один файл для dev (initdb), stage (accessory Kamal) и prod (провижининг db-1).
-- Идемпотентен: повторный запуск ничего не ломает.
--
-- Переменные psql (-v): dbname, app_password, migrator_password, readonly_password, backup_password.
-- FTS-конфигурации, коллации и функции поиска создаёт миграция platform_0001 (шаг 0.9).
\set ON_ERROR_STOP on

-- Роли
SELECT format('CREATE ROLE %I LOGIN', r)
FROM (VALUES ('app'), ('migrator'), ('readonly'), ('backup')) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)
\gexec

ALTER ROLE app PASSWORD :'app_password';
ALTER ROLE migrator PASSWORD :'migrator_password';
ALTER ROLE readonly PASSWORD :'readonly_password';
ALTER ROLE backup PASSWORD :'backup_password';

-- app: процессы приложения. Параметры из ADR-0005 и ADR-0020 §4:
-- без параллельных планов и generic plans, короткие таймауты.
ALTER ROLE app SET max_parallel_workers_per_gather = 0;
ALTER ROLE app SET plan_cache_mode = force_custom_plan;
ALTER ROLE app SET statement_timeout = '5s';
ALTER ROLE app SET idle_in_transaction_session_timeout = '30s';

-- migrator: владелец схем и объектов, выполняет Alembic. Не ждёт блокировки дольше 3 с.
ALTER ROLE migrator SET lock_timeout = '3s';
ALTER ROLE migrator SET statement_timeout = 0;

-- search_path: функции Procrastinate вызываются без схемы (docs/spikes/0.8), таблицы
-- модулей — всегда со схемой. Схему procrastinate создаёт миграция platform_0001.
ALTER ROLE app SET search_path = public, procrastinate;
ALTER ROLE migrator SET search_path = public, procrastinate;
ALTER ROLE readonly SET search_path = public, procrastinate;

-- readonly: аналитика и отладка, только чтение.
ALTER ROLE readonly SET default_transaction_read_only = on;
ALTER ROLE readonly SET statement_timeout = '30s';

-- backup: логические выгрузки и мониторинг.
GRANT pg_read_all_data TO backup;
GRANT pg_monitor TO backup;

-- База принадлежит migrator: он создаёт схемы модулей миграциями.
ALTER DATABASE :"dbname" OWNER TO migrator;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO app, readonly, backup;

\connect :"dbname"

-- Расширения (нужен суперпользователь).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- public: только для объектов расширений, создавать в нём нельзя никому, кроме суперпользователя.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app, readonly, migrator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app, readonly;

-- Права по умолчанию на объекты, которые migrator создаст миграциями.
ALTER DEFAULT PRIVILEGES FOR ROLE migrator GRANT USAGE ON SCHEMAS TO app, readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator GRANT USAGE, SELECT ON SEQUENCES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator GRANT EXECUTE ON FUNCTIONS TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator GRANT SELECT ON TABLES TO readonly;
