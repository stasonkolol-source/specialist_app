# PostgreSQL / PostGIS / S3 lab

Воспроизводимый стенд для отчёта `../07-postgres-lab-and-infra.md` (дата прогона: 2026-09-26).
Нужны только Docker (Compose v2) и bash. На хост ничего не устанавливается, все клиенты (psql, pgbench, aws-cli, boto3) работают в контейнерах.

## Что внутри

| Путь | Назначение |
|---|---|
| `docker-compose.yml` | проект `specialist-lab`: `postgres` (порт 127.0.0.1:55432), профиль `bench` (клиент pgbench), профиль `s3` (Garage, SeaweedFS, RustFS, imgproxy), профиль `tools` (s3test на python+boto3, aws-cli) |
| `postgres/Dockerfile` | `postgres:18.6-trixie` + `postgresql-18-postgis-3` (3.6.4) из PGDG; опционально pgvector и pg_cron |
| `sql/00_extensions.sql` | расширения, версии, `uuidv7()`, pg_cron, pgvector |
| `sql/01_locale_providers.sql` | builtin / libc / ICU: `lower()`, regex, pg_trgm и FTS на кириллице |
| `sql/02_fts_ru_sr.sql` | FTS для ru/sr: стеммеры, unaccent, IMMUTABLE, кастомные конфигурации, websearch/prefix, ранжирование |
| `sql/03_search_functions.sql` | итоговые функции: `f_unaccent`, `sr_cyr2lat`, `search_norm`, `sr_unaccent`, `q_all`, `tsvector_agg` |
| `sql/04_trgm_typos_translit.sql` | опечатки (pg_trgm), кириллица и латиница, межъязыковой поиск через таксономию |
| `sql/05_geo_basics.sql` | PostGIS: точка в полигоне, `ST_DWithin`, KNN, geography или geometry |
| `sql/06_i18n_collations.sql` | JSONB или таблица переводов, fallback, ICU-коллации ru/sr, недетерминированные коллации |
| `sql/10_schema.sql` … `sql/15_indexes_search.sql` | схема, справочники, генерация данных, FK-индексы, read-model, поисковые индексы |
| `sql/16_crosslang_demo.sql` | полнота и точность: своё FTS, обогащённое FTS, таксономия |
| `sql/bench/*.sql` | 42 запроса для `EXPLAIN (ANALYZE, BUFFERS)`: a — поиск специалистов, b — доска заявок, c — матчинг подписок, d — автодополнение, e — поиск по имени |
| `sql/pgbench/*.sql` | смешанная нагрузка для pgbench: 7 типов чтения и 2 типа записи |
| `scripts/setup_all.sh` | прогоняет все SQL-шаги по порядку (00–03, 10–15, затем 04, 05, 06, 16) |
| `scripts/bench_in_container.sh` | N+1 прогонов каждого запроса в одной сессии; 1-й прогон «холодный», остальные дают медиану |
| `scripts/pgbench_run.sh` | pgbench на 1, 8, 16 и 32 клиентов с перцентилями по каждому скрипту |
| `s3/*` | конфигурации S3-серверов и `s3_presign_test.py` (presigned PUT/GET/POST, CORS, imgproxy) |
| `results/` | сырые результаты: выводы SQL, планы (`results/bench*/`), сводки TSV, pgbench, S3 |

## Как воспроизвести

```bash
cd docs/research/lab
docker compose -p specialist-lab build postgres
docker compose -p specialist-lab up -d postgres            # ждём healthy

./scripts/setup_all.sh                                      # все SQL-шаги, 38 с на M4 Pro; выводы в results/*.txt

# EXPLAIN-бенчмарк (10 тёплых прогонов на запрос)
docker compose -p specialist-lab exec -T -e N=10 postgres bash /lab/scripts/bench_in_container.sh
docker compose -p specialist-lab exec -T -e N=10 -e TAG=noparallel \
  -e PGOPTIONS="-c max_parallel_workers_per_gather=0" postgres bash /lab/scripts/bench_in_container.sh

# нагрузочный тест из отдельного контейнера (2 CPU)
docker compose -p specialist-lab --profile bench run --rm -e TAG=custom_noparallel \
  -e PGOPTIONS="-c max_parallel_workers_per_gather=0 -c plan_cache_mode=force_custom_plan" \
  bench /lab/scripts/pgbench_run.sh

# S3 + imgproxy
docker compose -p specialist-lab --profile s3 up -d garage seaweedfs rustfs imgproxy
docker compose -p specialist-lab --profile tools run --rm s3test
docker compose -p specialist-lab --profile tools run --rm awscli --endpoint-url http://garage:3900 --region garage s3 ls s3://lab
#   (для awscli передайте AWS_ACCESS_KEY_ID и AWS_SECRET_ACCESS_KEY из docker-compose.yml через -e)

# уборка: контейнеры и тома этого проекта (файлы лаборатории остаются)
docker compose -p specialist-lab --profile s3 --profile tools --profile bench down -v
# при желании удалить и собранный образ: добавьте --rmi local
```

## Параметры Postgres в лаборатории

Настройки заданы в `docker-compose.yml`: `shared_buffers=1GB`, `effective_cache_size=2GB`, `work_mem=16MB`, `maintenance_work_mem=512MB`, `random_page_cost=1.1`, `effective_io_concurrency=200`, `jit=off`, `max_parallel_workers_per_gather=2` (по умолчанию; в отчёте есть сравнение с 0), `shared_preload_libraries=pg_stat_statements,pg_cron`.

Лимиты контейнера: 2.5 GB RAM и 4 выделенных ядра (`cpuset: "0-3"`). Не используйте `cpus: 4`: это CFS-квота, и под нагрузкой она даёт троттлинг с хвостами по 50–80 мс (см. `results/pgbench/cfs_throttling_note.txt`).

Кластер инициализирован так: `--locale-provider=builtin --builtin-locale=C.UTF-8`, при этом `LC_CTYPE=en_US.utf8`. Это важно, потому что pg_trgm при `LC_CTYPE=C` не видит кириллицу (см. `results/01_locale_providers.txt`).

## Оговорки

Цифры получены на ноутбуке Apple M4 Pro (Docker VM linux/arm64, данные целиком в shared_buffers). Это не продакшен: ядра M4 быстрее типичных облачных vCPU, диск и сеть не участвуют. Замеры годятся для сравнения вариантов между собой и для оценки порядка величин, а не для SLA.

Данные синтетические, генерация детерминирована (`setseed`). Районы — это гексагоны вокруг центров городов, а не реальные границы.
