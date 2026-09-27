# ADR-0015: Хостинг и деплой — Hetzner Cloud (DE), Cloudflare на краю, Kamal 2, GitHub Actions

- **Статус:** принято
- **Дата:** 2026-09-26
- **Связанные документы:** [research/07-postgres-lab-and-infra.md §4](../research/07-postgres-lab-and-infra.md#4-часть-b-инфраструктура), [research/05-legal-and-payments-serbia.md §1.8](../research/05-legal-and-payments-serbia.md#18-представитель-в-сербии-и-трансграничная-передача), [ARCHITECTURE.md §16](../ARCHITECTURE.md#16-инфраструктура-и-devops), [ADR-0005](0005-postgresql-postgis-data-platform.md)

## Контекст

- **Аудитория** — в Сербии: Белград и Нови-Сад.
- **Закон о персональных данных (ZZPL).** Локализации в Сербии не требует. Передача данных в страны ЕС и Конвенции 108 разрешена без SCC. Нужен DPA с провайдером (ст. 45), хостинг только в DE или FI.
- **Бюджет стартапа.** Команда 1–2 человека, выделенного DevOps нет.
- **Задержки из Белграда:** Нюрнберг (Hetzner nbg1) ≈32 мс, Фалькенштайн ≈33 мс, Франкфурт ≈38 мс. Разница между ними в пределах шума.
- **Hetzner Cloud.** В 2026 году цены дважды выросли (CX33 теперь €8,49/мес), managed PostgreSQL нет.
- **Панели Coolify и Dokploy** в 2026 году получили серии критических уязвимостей.

## Рассмотренные варианты

| Вариант | Стоимость MVP / через год | Плюсы | Минусы |
|---|---|---|---|
| **Hetzner Cloud + self-managed PostgreSQL** | ≈ €28 + $0–35 / ≈ €61–67 (до €138 с dedicated CCX23 для БД) + $75–160 в месяц | Дёшево, EU, полный контроль расширений, свои FTS-конфигурации | Бэкапы и restore на нас |
| DigitalOcean (droplets + managed PostgreSQL с PostGIS) | ≈ $32–55 / ≈ $224–262 в месяц | Меньше ops | Дороже в 1,2–3 раза; ограничения managed-сервиса (superuser, словари) |
| AWS или GCP | Заметно дороже | Всё managed | Цена, сложность |
| Сербские провайдеры (mts, Orion, mCloud) | Сопоставимо | Минимальная задержка | Нет managed PostgreSQL, API и Terraform, хуже автоматизация |
| Деплой: Kamal 2 / Compose + Caddy / Coolify / k3s | — | Kamal даёт zero-downtime, откат и pre-deploy hook для Alembic без веб-панели | k3s избыточен до 3+ нод; Coolify и Dokploy — уязвимости |

## Решение

**Окружения**

| Окружение | Где | Состав |
|---|---|---|
| `dev` | Ноутбук | `docker compose`: наш образ PostgreSQL 18 + PostGIS, Valkey 9.1, Garage (S3). Процессы `web`, `bot`, `worker` запускаются через `uv run` с hot reload. Бот — отдельный тестовый бот, в dev работает в polling-режиме |
| `stage` | Hetzner CX23 (€5,49) | Всё на одной VM, отдельные бот, R2-бакеты и БД. Анонимизированные seed-данные. Тестовая среда Telegram для платежей |
| `prod` | Hetzner nbg1 или fsn1 | См. ниже |

**Продакшен на старте (MVP)**

| Компонент | Где | Примерная цена |
|---|---|---|
| VM `app-1` — CX33 (4 vCPU, 8 GB) | Процессы из одного образа `ghcr.io/<org>/backend:<sha>`: `web` (API + admin), `bot`, `worker`, `worker-media` (ограничения CPU и памяти); Valkey как accessory Kamal; kamal-proxy (TLS) | €8,49 |
| VM `db-1` — CX33 | PostgreSQL 18 + PostGIS (PGDG-пакеты, `initdb` с UTF-8 `LC_CTYPE`), pgBackRest; порт закрыт firewall, доступ только из private network Hetzner | €8,49 |
| Бэкапы Hetzner для VM | 20% от цены VM | ≈ €3,40 |
| IPv4 | Публичные адреса | ≈ €1 **[Допущение: вторичный источник]** |
| Hetzner Object Storage | WAL-архив и бэкапы pgBackRest | €6,49 |
| Вторая копия бэкапов (Backblaze B2) | Другой провайдер для DR | ≈ $0,2 |
| Cloudflare | DNS, прокси и WAF, одно бесплатное rate-limit-правило, Workers Static Assets для Mini App, R2 + CDN для медиа, Cloudflare Access (Zero Trust Free) перед `/admin` | $0 + R2 по объёму |
| Sentry Developer (при росте — Team $26) или GlitchTip | Ошибки | $0 |
| Grafana Cloud Free (метрики, логи, трейсы через Grafana Alloy) | Наблюдаемость | $0 |
| UptimeRobot + Healthchecks.io | Uptime, cron, бэкапы, heartbeat воркеров | $0 |
| **Итого** | | **≈ €28 в месяц + $0–35 на внешние сервисы (R2 $0–5, B2 ≈ $0,2, Sentry и Grafana $0, GitHub $0–8, AI < $20)** |

Почему две VM, а не одна (≈€17): транскодирование видео и всплески рассылок не должны отнимать CPU у PostgreSQL, а БД остаётся изолированной по сети.

**Доменная схема**

| Домен | Что обслуживает |
|---|---|
| `app.<domain>` | Mini App и веб-оболочка (Cloudflare Workers Static Assets). `app.<domain>/api/*` проксируется на `app-1`: один origin, поэтому нет CORS и preflight-запросов. Правило Bot API 10.2 касается методов Mini App, а весь SPA и так живёт на `app.<domain>` |
| `api.<domain>` | API для мобильных клиентов и вебхуков: Telegram, позже Apple, Google, платёжный шлюз |
| `cdn.<domain>` | R2-бакет `media` |
| `admin.<domain>` | SQLAdmin (`/admin` в процессе `web`) за Cloudflare Access |

**Бэкапы и восстановление**

- pgBackRest: полный бэкап раз в неделю, дифференциальный ежедневно, WAL непрерывно (`archive-async`). Хранение — 4 недели полных бэкапов и PITR на 14 дней.
- **Ежемесячный автоматический restore** на временную VM с проверкой `postgis_full_version()` и smoke-тестами, отчёт в Healthchecks.io.
- Цели: **RPO ≤ 5 мин, RTO ≤ 2 ч** на старте. При доступности 99,5% (≈ 3,6 ч простоя в месяц) один инцидент с восстановлением укладывается в бюджет.

**CI/CD — GitHub Actions**

- Pull request: `ruff`, `mypy`, `import-linter`, pytest на PostGIS service-контейнере (наш образ), `alembic check`, проверка `show_trgm('тест')`, `oasdiff` против `main`, генерация `api-client` и сборка фронтенда, Vitest.
- `main` → сборка образа (amd64) → `ghcr.io` (образы закреплены по digest) → деплой на stage.
- Prod — ручное подтверждение. `kamal deploy`: pre-deploy hook `alembic upgrade head` (expand/contract), healthcheck `/up`, zero-downtime, `kamal rollback` на предыдущий образ.
- Mini App — `wrangler deploy` в Cloudflare. Версия билда сверяется с `/client-config`.

**Секреты** — SOPS + age: зашифрованные файлы в git, `.kamal/secrets` вызывает `sops -d`, приватный ключ хранится в менеджере паролей и в секрете GitHub.

**Безопасность хоста**
- SSH только по ключу, из allowlist или через Tailscale;
- `ufw` и firewall Hetzner;
- unattended-upgrades;
- Docker без публикации портов наружу, кроме kamal-proxy.

**Масштабирование** (ARCHITECTURE.md §18):
- `app-2` за Hetzner LB (≈ €7,49 **[Допущение: вторичный источник]**);
- `db-1` → CX43 и потоковая реплика;
- отдельная VM под `worker-media`;
- PgBouncer.

Переход на managed PostgreSQL — при появлении требований к HA или при недостатке ops-ресурса.

## Последствия

**Положительные**

- Минимальная стоимость при EU-юрисдикции, которая соответствует ZZPL.
- Нет vendor lock-in: Docker-образы, Kamal и PostgreSQL переносятся к любому провайдеру.
- Деплой без простоя с откатом одной командой; миграции выполняются один раз и предсказуемо.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| Self-managed БД: нет HA, bus factor | PITR, ежемесячный restore-тест, runbook, реплика по мере роста; переход на managed — не архитектурное изменение |
| Hetzner может снова поднять цены | Нет lock-in; переезд — это новый `deploy.yml` и restore из бэкапа |
| Одна VM приложения — единая точка отказа | Второй экземпляр за LB при росте; до тех пор RTO — минуты (новая VM + `kamal setup`) |
| Лимиты бесплатных тарифов наблюдаемости | Семплирование трейсов и логов, переход на платные тарифы по факту |

**Что сделать**

- Terraform (провайдеры `hcloud` и `cloudflare`) для VM, firewall, DNS и бакетов — воспроизводимость окружений.
- Runbooks: восстановление БД, ротация секретов, инцидент утечки данных (72 ч, Poverenik), откат релиза.
