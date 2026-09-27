# ADR-0005: Платформа данных — PostgreSQL 18 + PostGIS 3.6, схема на модуль, UUIDv7

- **Статус:** принято
- **Дата:** 2026-09-26
- **Связанные документы:** [research/07-postgres-lab-and-infra.md](../research/07-postgres-lab-and-infra.md), [ARCHITECTURE.md §7](../ARCHITECTURE.md#7-модель-данных), [ADR-0002](0002-modular-monolith.md), [ADR-0006](0006-search-in-postgresql.md), [ADR-0008](0008-background-jobs-and-outbox.md)

## Контекст

PostgreSQL задан вводными. Вопросы, которые проверялись: какая версия, какие расширения, как хранить гео, поиск, мультиязычные справочники, очередь задач, и не нужна ли отдельная технология. Лаборатория в Docker (arm64) проверила это на синтетических данных масштаба «год после запуска»:

| Сущность | Объём |
|---|---|
| Специалисты | 50k |
| Позиции прайса | 274k |
| Заявки | 300k |
| Отклики | 450k |
| Размер базы | 638 MB |

## Рассмотренные варианты

- **Версия.**
  - PostgreSQL 18.6: GA, `uuidv7()`, асинхронный I/O, `LIKE` с недетерминированными коллациями.
  - PostgreSQL 19: на 2026-09-26 только beta 4, GA ожидается в октябре.
- **Гео.**
  - PostGIS в той же БД.
  - Хранить координаты числами и считать расстояния в приложении — отвергнуто: нет индексов, нет полигонов районов.
- **Отдельные хранилища** (поисковый движок, брокер, кэш-БД). Отложены: лаборатория показала запас около 10× к ожидаемому пику первого года даже с поправкой ×2–4 на облачные vCPU ([ADR-0006](0006-search-in-postgresql.md)).

## Решение

1. **PostgreSQL 18.x (сейчас 18.6) + PostGIS 3.6.x (сейчас 3.6.4)**. Переход на PG 19 — не раньше 19.1–19.2. После `pg_upgrade` переиндексируем FTS и pg_trgm, как требуют release notes.
2. **Расширения:**

   | Когда | Расширения |
   |---|---|
   | С первого дня | `postgis`, `pg_trgm`, `unaccent`, `btree_gin`, `btree_gist`, `pg_stat_statements` |
   | По мере надобности | `pgvector` 0.8.x (семантический поиск и рекомендации), `pg_cron` (требует `shared_preload_libraries` и рестарта) |

3. **Инициализация кластера — только с UTF-8 `LC_CTYPE`.** При `LC_CTYPE=C` pg_trgm молча перестаёт видеть кириллицу (`show_trgm('Електричар') = {}`), даже с ICU- и builtin-провайдером.

   ```text
   initdb --encoding=UTF8 --locale-provider=builtin --builtin-locale=C.UTF-8 --lc-ctype=C.UTF-8 --lc-collate=C.UTF-8
   ```

   - Сортировка для пользователя — явными ICU-коллациями `ru-RU`, `sr-Latn-RS`, `sr-Cyrl-RS` в выражениях и индексах.
   - Бонус builtin C.UTF-8: btree поддерживает `LIKE 'prefix%'`, а индексы не зависят от версии glibc.
   - Проверка `SELECT show_trgm('тест')` входит в smoke-тест окружения и CI.
4. **Роли и параметры.**
   - Роль приложения `app`:

     ```sql
     ALTER ROLE app SET max_parallel_workers_per_gather = 0;          -- параллельные планы на OLTP медленнее в 2,4–8,4 раза
     ALTER ROLE app SET plan_cache_mode = 'force_custom_plan';        -- generic plan PostGIS-запроса: 24,5 мс против 4,5 мс; +36% TPS
     ALTER ROLE app SET statement_timeout = '5s';
     ALTER ROLE app SET idle_in_transaction_session_timeout = '30s';
     ```

     **[Допущение]** `force_custom_plan` важен и для psycopg 3: после 5 выполнений он тоже переходит на server-side prepared statements. Замер в лаборатории делался с `pgbench -M prepared`, как у asyncpg; поведение psycopg проверить в спайке.
   - Отдельные роли: `migrator` (DDL, `lock_timeout = '3s'`), `readonly` (аналитика; параллелизм разрешён), `backup`.
5. **Схема на модуль** (`identity`, `jobs`, …), FK между схемами — только по DAG модулей ([ADR-0002](0002-modular-monolith.md)). Очередь задач Procrastinate — в своей схеме ([ADR-0008](0008-background-jobs-and-outbox.md)).
6. **Ключи.**
   - Сущности — `uuid` v7: генерируется в приложении (`uuid.uuid7()` из Python 3.14), дефолт в БД — `uuidv7()`. Монотонность проверена на 100k значениях.
   - Справочники — `int identity`.
   - Известный минус: UUIDv7 раскрывает время создания записи, для наших сущностей это приемлемо.
7. **Гео.**
   - Точки — `geography(Point,4326)`: метры, KNN.
   - Границы районов — `geometry(MultiPolygon,4326)` + GiST, проверка через `ST_Covers`.
   - Подписки по радиусу материализуются в `geometry(Polygon)` через `ST_Buffer(geography, r)`.
   - GiST по разреженным колонкам — частичный `WHERE col IS NOT NULL`: в 10 раз меньше.
8. **Миграции** — Alembic, стратегия expand/contract:
   - каждая миграция совместима с предыдущей версией приложения;
   - `SET lock_timeout` в начале миграции;
   - индексы создаются `CREATE INDEX CONCURRENTLY` в `autocommit_block`;
   - миграции запускаются один раз в pre-deploy hook ([ADR-0015](0015-hosting-and-deployment.md)).
9. **Пулинг.** Пул соединений в приложении (psycopg_pool); первые запросы нового соединения прогреваются, потому что холодное планирование PostGIS занимает 6–9 мс. PgBouncer — при росте числа процессов. В transaction mode учитываем prepared statements: PgBouncer ≥ 1.22 с `max_prepared_statements` (для psycopg — с libpq 17).
10. **Эксплуатация.**
    - Self-managed PostgreSQL на отдельной VM с pgBackRest: полный бэкап раз в неделю, дифференциальный ежедневно, WAL непрерывно. Копии — в объектном хранилище и у второго провайдера.
    - Ежемесячный автоматический тестовый restore.
    - Детали — в [ADR-0015](0015-hosting-and-deployment.md).
11. **Локальная разработка и CI** — собственный образ на базе `postgres:18.6-trixie` + `postgresql-18-postgis-3` из PGDG (Dockerfile в `docs/research/lab/postgres/`). Официальный `postgis/postgis` до сих пор только amd64. Образ закрепляется по digest и зеркалируется в GHCR.

## Последствия

**Положительные**

- Одна СУБД на OLTP, поиск, гео и очередь задач: одна точка бэкапа, одна модель консистентности, минимум инфраструктуры.
- Запас производительности. Смешанная нагрузка на 4 ядрах ноутбука даёт ≈ 2 800 TPS (p95 9 мс); одна транзакция pgbench — один SQL-запрос, а не вызов API. С поправкой ×2–4 на облачные vCPU это около 10× к ожидаемому пику первого года (десятки RPS) и 2–5× к проектной ёмкости. Цифры перепроверяются на целевой VM.
- Мультиязычные справочники в JSONB с индексами по выражению и ICU-коллацией: 0,1 мс против 136 мс у таблицы переводов с fallback.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| Self-managed PostgreSQL: bus factor, незамеченные сломанные бэкапы | Автоматический restore-тест, алерты Healthchecks.io, runbook. Переход на managed (DigitalOcean или Scaleway с PostGIS) остаётся доступным, если на managed проверены свои TS-конфигурации, `CREATE COLLATION` и `LC_CTYPE` |
| Одна БД — одна точка отказа | PITR, реплика по мере роста, RPO ≤ 5 мин и RTO ≤ 2 ч на старте |
| Замеры сделаны на ноутбуке, база целиком в `shared_buffers` | Перед запуском прогнать `bench_in_container.sh` и `pgbench_run.sh` из лаборатории на целевой VM |

**Что сделать**

- `infra/postgres/`: Dockerfile (PG 18 + PostGIS из PGDG, закреплён по digest) и init-скрипты — локаль, роли с параметрами, расширения, FTS-конфигурации из [ADR-0006](0006-search-in-postgresql.md).
- Smoke-тест в CI: `SHOW lc_ctype`, `SELECT show_trgm('тест')`, `postgis_full_version()`.
- Спайк: psycopg 3 + prepared statements + `force_custom_plan` на типовых PostGIS-запросах.
- pgBackRest, ежемесячный автоматический restore-тест и прогон бенчмарков лаборатории на целевой VM — до публичного запуска.
