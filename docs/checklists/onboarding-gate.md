# Ворота онбординга на проде — чек-лист

Шаг 3.4 [плана](../DEVELOPMENT_PLAN.md#34-ворота-онбординга-на-проде). Реальные персональные данные
founding-специалистов попадают на прод только после этого чек-листа: каждый пункт отмечен, у
каждого — доказательство (ссылка на прогон, скриншот, запись в runbook). Черновик подготовлен
2026-10-04: пункты и способ проверки уже здесь, отметки ставятся на прогоне перед стартом онбординга
(ориентир — неделя 7 MVP, ≈ 2026-12-11, или дата, которую назначит владелец). Подписанный чек-лист —
результат шага 3.4: после него основатели начинают онбординг.

Статусы: **✅** проверено (дата, кто, доказательство); **⏳** не проверено; **❌** не прошло — блокер
(ссылка на задачу); **N/A** — не применимо (почему).

## 0. Предпосылки

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 0.1 | Шаги-зависимости приняты: 1.7, 2.5b, 2.10, 2.11, 2.12b, 3.2, 3.3 | Статусы в таблице шагов [плана](../DEVELOPMENT_PLAN.md#4-обзор-шагов); `make plan-check` | ⏳ |
| 0.2 | Prod выкачен и отвечает (3.1c) | `curl -s https://api.<domain>/up`; в логе старта `web_started` — `env: production` и версия релиза | ⏳ |

## 1. Бэкап и restore-тест свежие

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 1.1 | Бэкап свежий в обоих репозиториях | `pgbackrest info` на `db-1`: полный — не старше 7 дней, diff — не старше суток, и в repo1 (Hetzner Object Storage), и в repo2 (Backblaze B2); проверка «pgBackRest» в Healthchecks зелёная | ⏳ |
| 1.2 | Архив WAL не отстаёт | `SosedWalArchiveLag` и `SosedWalArchiveFailing` (`infra/monitoring/rules/sosed.yaml`) молчат; `pg_stat_archiver_last_archive_age` prod ≤ 5 мин | ⏳ |
| 1.3 | restore-тест свежий и зелёный | Последний `restore-test.yml` — не старше месяца и зелёный; RPO ≤ 5 мин и RTO ≤ 2 ч записаны в [`infra/runbooks/restore.md`](../../infra/runbooks/restore.md); пароль шифрования — копия из менеджера паролей (K10a), а не с сервера | ⏳ |

## 2. Алерты доходят

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 2.1 | Тестовая ошибка backend видна в Sentry (K20) | `make kamal ARGS="app exec -d production 'python -m app.entrypoints.cli sentry-test'"` → событие с этим id в Sentry, `environment=production` | ⏳ |
| 2.2 | Тестовая ошибка Mini App видна в Sentry | Ошибка из Mini App prod — в проекте `tma`, со своим релизом (sha деплоя), окружением `production` и читаемым стеком. CSP пускает адрес приёма из `TMA_SENTRY_DSN` (`connect-src`); initData вычищается до отправки; source maps загружает деплой при `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `TMA_SENTRY_PROJECT` (K20) | ⏳ |
| 2.3 | Тестовый алерт доходит до канала K35a | [`prod-bootstrap.md`](../../infra/runbooks/prod-bootstrap.md), раздел 8, п. 8: Grafana — Contact point → Test; Healthchecks — остановить worker на stage; UptimeRobot — остановить bot на stage. Письма пришли | ⏳ |
| 2.4 | Метрики prod доходят до Grafana Cloud (K35) | Explore → `up{env="production"}`: роли, `node` (`app-1`, `db-1`) и `postgres` — у всех 1 (раздел 8, п. 4) | ⏳ |
| 2.5 | В Loki нет персональных данных | Раздел 8, п. 9: запрос по телефонам, e-mail, JWT и initData за сутки пуст; 50 строк `role="web"` просмотрены глазами | ⏳ |

## 3. Модерация: дежурные и SLA

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 3.1 | В prod-чате модераторов есть дежурные (K29, Q21) | В чате — prod-бот и модераторы из списка K29, у них роль `moderator` на проде; график дежурств 08:00–23:00 записан; `TELEGRAM_MODERATORS_CHAT_ID` prod задан | ⏳ |
| 3.2 | Тестовый профиль проходит P2 за SLA | Тестовый профиль исполнителя через prod-бота → кейс P2 → карточка в prod-чате → решение кнопкой ≤ 30 мин в 08:00–23:00 (ARCHITECTURE §14.2); время — из `moderation.cases` | ⏳ |

## 4. Приватность: политика, удаление, выгрузка

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 4.1 | В prod действуют утверждённые правила и политика (K22) | Владелец утвердил тексты; `legal_versions` client-config prod указывает на утверждённые версии; `GET https://api.<domain>/api/v1/client-config` → `legal_documents.privacy` — та же версия и дата редакции, что на S48 и в `/privacy` бота | ⏳ |
| 4.2 | Политика перечисляет обработчиков, которые реально включены (OpenAI и Anthropic — если ключи уже стоят, PostHog, Sentry, Cloudflare, Hetzner) | Раздел 5 политики prod-версии сверен с [приложением А](#приложение-а-внешние-обработчики-данных): флаги `describe()` в логах старта prod (`web_started`, `worker_started`), Variables и ключи из колонки «Включён, если». Каждый включённый обработчик есть в политике | ⏳ |
| 4.3 | Регион каждого обработчика совпадает с политикой | Sentry — организация в регионе EU (DSN вида `…ingest.de.sentry.io`); Grafana Cloud — стек в регионе EU; Backblaze B2 — аккаунт в регионе EU (endpoint `s3.eu-central-…`); PostHog — `eu.i.posthog.com`; R2 — EU jurisdiction (Terraform); Hetzner — `nbg1` или `fsn1`. Не так — правка политики до старта | ⏳ |
| 4.4 | Оператор данных и почта в тексте — настоящие | Prod не стартует с заглушкой `[TODO …]` в `LEGAL_OPERATOR_NAME` и `LEGAL_CONTACT_EMAIL`; в разделе 1 политики на S48 — оператор и почта | ⏳ |
| 4.5 | Удаление аккаунта проверено на тестовом аккаунте в prod | S45 → запрос → через 7 дней аккаунт обезличен ([`deletion-request.md`](../../infra/runbooks/deletion-request.md), раздел 4) | ⏳ |
| 4.6 | Выгрузка данных проверена на тестовом аккаунте в prod | `cli export-user-data <id>` через `kamal app exec -d production` по [`data-export.md`](../../infra/runbooks/data-export.md): все разделы на месте, запись `privacy.user_data.exported` в `audit_log` | ⏳ |
| 4.7 | Удаление персоны в PostHog по `UserDeleted` (2.12b) | В `production` заданы `ANALYTICS_POSTHOG_PERSONAL_API_KEY` (ключ `sosedi-deletion`, scope `person` write) и `ANALYTICS_POSTHOG_PROJECT_ID`; в логе старта воркера нет `analytics_person_deletion_disabled`; у тестового аккаунта из 4.5 в логе воркера — `analytics_person_forgotten` с `persons_found` 1, в PostHog → Persons его нет. PostHog на проде выключен (`posthog: false`) — N/A, и пункт 5.2 тоже | ⏳ |

## 5. Аналитика

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 5.1 | PostHog EU подключён к prod (K32) | `posthog: true` в `worker_started` prod; ключ проекта — в Variables environment `production` | ⏳ |
| 5.2 | События онбординга видны в PostHog | От тестового аккаунта — `user_registered`, `onboarding_completed`, `write_access_granted` с `environment = production` в проекте PostHog EU | ⏳ |

## 6. Prod-бот

| № | Пункт | Как проверить | Статус |
|---|---|---|---|
| 6.1 | Main Mini App на `https://app.<domain>` (K40a) | BotFather → Main Mini App; ссылка `t.me/<prod-бот>?startapp=h` открывает Главную | ⏳ |
| 6.2 | Ссылка на политику конфиденциальности в настройках бота (K40a) | BotFather → Privacy Policy — ссылка на действующую редакцию (страница на `app.<domain>`); `/privacy` в prod-боте отвечает той же версией и датой, что S48 | ⏳ |

## Решение

| Дата | Решение (go / no-go) | Кто | Комментарий |
|---|---|---|---|
| | | | |

## Приложение А. Внешние обработчики данных

Инвентаризация по коду на 2026-10-04 — подробно в [ARCHITECTURE §13.6](../ARCHITECTURE.md#136-внешние-обработчики-данных).
Для пункта 4.2: включённый на проде обработчик должен быть в разделе 5 политики prod-версии. На
2026-10-04 он есть у всех строк «Да» (черновик `privacy/draft-1`).

| Сервис | Что получает | Включён, если | Как проверить в prod | В политике |
|---|---|---|---|---|
| Telegram | Данные входа из `initData`, сообщения бота и уведомления, контакт из `requestContact` | Всегда | — | Да |
| Hetzner Cloud | Всё: VM, PostgreSQL, Valkey, логи, бэкапы VM | Всегда | `location` в `infra/terraform/prod` | Да |
| Hetzner Object Storage | Зашифрованные бэкапы БД (repo1) | Ключи `PGBACKREST_REPO1_*` | `pgbackrest info` (1.1) | Да, строка Hetzner |
| Cloudflare | Весь HTTP-трафик (WAF, Workers), медиа в R2, e-mail персонала (Access) | Всегда | Terraform `zone`, `prod` | Да |
| OpenAI | Тексты без контактов, имени и id автора; фото 800 px без EXIF | `AI_OPENAI_API_KEY` (K25) | `ai_moderation` в `describe()` | Да |
| Anthropic | Тексты авторов уровня 0 и с флагом, без контактов, имени и id автора | `AI_ANTHROPIC_API_KEY` (K26) | `ai_classifier` в `describe()` | Да |
| PostHog (EU) | Серверные события по внутреннему UUID, без ПД в свойствах | `ANALYTICS_POSTHOG_API_KEY` (K32) | `posthog` в `describe()` | Да |
| Sentry | Ошибки backend после маскирования; ошибки Mini App | `SENTRY_DSN`; Variable `TMA_SENTRY_DSN` | `sentry` в `describe()`; 2.1, 2.2 | Да |
| Grafana Cloud | Метрики без ПД; логи ролей с маскированием | Variable `GRAFANA_CLOUD_PROM_URL` и `GRAFANA_CLOUD_TOKEN` | accessory `alloy` на `app-1` (2.4) | Да |
| Backblaze B2 | Зашифрованные бэкапы БД (repo2) | Ключи `PGBACKREST_REPO2_*` | `pgbackrest info` (1.1) | Да |
| Healthchecks.io | Только пинги, без данных пользователей | Ping URL воркера, pgBackRest, restore-теста | `heartbeat` в `describe()` | Нет — ПД не получает |
| UptimeRobot | Только запросы к публичным `/up` и Mini App | Стек `infra/terraform/monitoring` (K34) | Мониторы в UptimeRobot | Нет — ПД не получает |
