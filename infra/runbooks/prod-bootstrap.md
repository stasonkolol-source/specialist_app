# Подъём prod с нуля

Порядок действий владельца и команды, после которых prod работает: VM и сеть в Hetzner (3.1a),
PostgreSQL на `db-1` (3.1b), Cloudflare, деплой, Access и prod-бот (3.1c). Код окружения —
`infra/terraform/prod`, `infra/terraform/zone`, `infra/postgres/provision.sh`, `infra/kamal`
(`deploy.production.yml`), `infra/workers/tma`, `.github/workflows/deploy.yml` (job `production`).
Пункты K и Q — [OWNER_CHECKLIST](../../docs/OWNER_CHECKLIST.md). Бэкапы pgBackRest и restore-тест —
шаг 3.2, раздел 7; наблюдаемость — 3.3, раздел 8; без них реальные данные на prod не приходят (ворота 3.4).

> Прогон «на сухую» — при первом подъёме prod (K38 и далее). Ни одна команда ниже до этого не
> запускалась против Hetzner и Cloudflare: проверены только `terraform validate`, план без сети,
> `kamal config -d production` на фиктивных значениях и синтаксис скриптов (2026-10-04).

Правила для всего runbook:
- все команды — в своём окне Терминала из `~/PycharmProjects/specialist_app`, не в чате;
- секрет — в менеджер паролей (K10a) **в момент создания**, потом в `.env` или GitHub;
- `terraform output` с ключами и `gh secret set --body` не используем: значение — только трубой;
- prod-значения в репозиторий не попадают: `terraform.tfvars` — без секретов, state — в `.gitignore`.

## 0. До начала

| Что | Пункт | По умолчанию |
|---|---|---|
| Stage поднят по [stage-bootstrap.md](stage-bootstrap.md), бенчмарки 0.26 приняты | 0.25a–e, 0.26 | размеры VM — CX33 |
| Название и домен под него | Q8, Q9 | «Соседи»; домен — тот же, что у stage |
| Self-managed PostgreSQL, RPO ≤ 5 мин, RTO ≤ 2 ч | Q27 № 12 | да |
| Где хранить секреты prod | Q1 | (б) секреты GitHub environment `production` |
| GitHub environment `production`: Settings → Environments → New → `production` → Deployment branches → Selected → `main`; **Required reviewers** → вы (и второй основатель) | K19, Q5 | репозиторий публичный — правило доступно на Free |
| Папка `specialist-prod` в менеджере паролей | K10a | — |

## 1. VM и сеть в Hetzner (3.1a)

Нужно: K38 (проект `specialist-prod` и токен), K15 (ваш публичный ключ; deploy-ключ prod —
**другой**, не stage), Q12 (регион, по умолчанию `nbg1`), Q13 (22-й порт `app-1` открыт, вход только
по ключу; у `db-1` SSH снаружи нет совсем), Q14 (state локальный).

1. Токен: `make secret NAME=HCLOUD_TOKEN TARGET=tf-prod`.
2. Deploy-ключ prod для CI (без пароля — его держит только ssh-agent CI):
   ```
   ssh-keygen -t ed25519 -N '' -C deploy-prod -f ~/.ssh/sosed_prod_deploy
   gh secret set DEPLOY_SSH_KEY --env production < ~/.ssh/sosed_prod_deploy
   ```
   Приватную часть — в менеджер паролей (`pbcopy < ~/.ssh/sosed_prod_deploy`, вставить, скопировать
   что-нибудь другое), затем `rm ~/.ssh/sosed_prod_deploy`.
3. `cp infra/terraform/prod/prod.tfvars.example infra/terraform/prod/terraform.tfvars` и вписать
   `ssh_public_keys`: ваш `~/.ssh/id_ed25519.pub` и `~/.ssh/sosed_prod_deploy.pub`. Секретов в этом
   файле нет.
4. ```
   make tf ENV=prod ARGS='init'
   make tf ENV=prod ARGS='plan'
   make tf ENV=prod ARGS='apply'
   make tf ENV=prod ARGS='output app_ipv4'
   make tf ENV=prod ARGS='output db_private_ip'
   ```
   Создаётся: сеть `sosed-prod` (10.20.0.0/16, подсеть 10.20.1.0/24), `app-1` (10.20.1.10) и `db-1`
   (10.20.1.20) на разных физических хостах, бэкапы Hetzner, защита от удаления, два firewall.
   Variables environment `production`: `PROD_HOST` = IPv4 `app-1`, `PROD_DB_IP` = `10.20.1.20`.
5. Проверка (≈ 3–5 минут на cloud-init обеих VM):
   ```
   ssh root@<PROD_HOST> 'cloud-init status --wait && docker network inspect kamal -f "{{(index .IPAM.Config 0).Subnet}}"'
   ssh -J root@<PROD_HOST> root@10.20.1.20 'cloud-init status --wait && ufw status && ls /usr/lib/postgresql/18/bin/postgres && pgbackrest version'
   nc -z -w3 $(make -s tf ENV=prod ARGS='output -raw db_ipv4' < /dev/null) 5432 && echo 'ОШИБКА: 5432 открыт' || echo 'порт БД снаружи закрыт'
   ```
   На `db-1` нет публичного SSH: вход — только `ssh -J root@<PROD_HOST> root@10.20.1.20`.
6. Копию `infra/terraform/prod/terraform.tfstate` — в менеджер паролей после каждого `apply` (Q14):
   с шага 3 в нём ключ сертификата Origin CA.
7. Готово, когда повторный `make tf ENV=prod ARGS='plan'` пишет «No changes».

## 2. PostgreSQL на db-1 (3.1b)

Нужно: K19 (секреты `production`), K10a (копии), K18 — только при SOPS (по умолчанию не нужен).

1. Пароли ролей — в своём Терминале командой `make gen-secret`: значение показывается один раз и
   лежит в буфере обмена — вставьте в менеджер паролей (K10a) и нажмите Enter; скрипт передаст его в
   GitHub (`gh secret set --env production`, через stdin) и сотрёт экран и буфер. Пароля
   суперпользователя нет: `postgres` входит только локально на `db-1`.
   ```
   for n in APP_DB_PASSWORD MIGRATOR_DB_PASSWORD READONLY_DB_PASSWORD BACKUP_DB_PASSWORD; do
     make gen-secret NAME=$n ENV=production || break
   done
   ```
2. Variable репозитория `PROD_DEPLOY` = `true` (Settings → Secrets and variables → Actions →
   Variables). С этого момента job `production` в `.github/workflows/deploy.yml` запускается — только
   вручную и только после вашего подтверждения.
3. Actions → deploy → Run workflow: `env` = `production`, `action` = `db-provision` → Approve. Job
   выполняет `make db-provision ENV=prod` (кластер с builtin C.UTF-8, `bootstrap.sql` — роли и
   расширения, как в dev и на stage; `pg_hba` — роли приложения только из подсети prod по TLS) и
   `make pg-smoke ENV=prod`.
4. Повторный запуск того же `db-provision` ничего не меняет и не перезапускает БД — это и есть
   проверка идемпотентности из плана.

То же с вашей машины, если пароли из менеджера паролей лежат в окружении (Q15):
`PROD_HOST=… PROD_DB_IP=10.20.1.20 make db-provision ENV=prod` и `make pg-smoke ENV=prod`.

WAL до шага 3.2 не архивируется (`archive_command = /bin/true`): реальных данных до ворот 3.4 нет.
Бэкапы включает тот же `db-provision`, когда в `production` есть ключи pgBackRest — раздел 7.

## 3. Cloudflare: зона, DNS, R2, Origin CA (3.1c)

Нужно: K11 (Account ID, Zone ID), K12 (токен `terraform`), K39 (R2 prod), Q8 и Q9 (домен).

1. Общий стек зоны — если ещё не применён при подъёме stage:
   ```
   make secret NAME=CLOUDFLARE_API_TOKEN TARGET=tf-zone
   cp infra/terraform/zone/zone.tfvars.example infra/terraform/zone/terraform.tfvars   # domain, cloudflare_zone_id
   make tf ENV=zone ARGS='init' && make tf ENV=zone ARGS='apply'
   ```
   Это Full (strict), Always HTTPS, TLS ≥ 1.2 и custom rules WAF: skip для webhook Telegram на `bot.`
   и `stage-bot.` (только с адресов Bot API), запрет `/admin` на хостах API.
2. `make secret NAME=CLOUDFLARE_API_TOKEN TARGET=tf-prod`; в `infra/terraform/prod/terraform.tfvars`:
   `cloudflare_enabled = true`, `domain`, `cloudflare_account_id`, `cloudflare_zone_id`; затем
   `make tf ENV=prod ARGS='plan'` и `ARGS='apply'`.
3. Сертификат Origin CA для kamal-proxy (`api.`, `bot.` и `admin.`) — сразу в секреты, минуя экран:
   ```
   make tf ENV=prod ARGS='output -raw origin_certificate_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_CERT --env production
   make tf ENV=prod ARGS='output -raw origin_private_key_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_KEY --env production
   ```
4. R2 prod (K39): R2 → Manage R2 API Tokens → Object Read & Write только на `sosed-prod-incoming`,
   `sosed-prod-media`, `sosed-prod-private` → `gh secret set S3_ACCESS_KEY_ID --env production` и
   `S3_SECRET_ACCESS_KEY`.
5. Variables environment `production`: `PROD_DOMAIN`, `CLOUDFLARE_ACCOUNT_ID`.
6. Проверка: `dig +short api.<домен>` и `dig +short bot.<домен>` — адреса Cloudflare; повторный
   `plan` — «No changes».

## 4. Prod-бот и секреты приложения (3.1c)

Нужно: K40a (бот, Main Mini App на `https://app.<домен>`, ссылка на политику), K19, K20 (DSN — по
желанию, обязательно к 3.3), K29 (prod-чат модераторов), K25 и K26 (AI — по желанию).

1. Variables `production`: `PROD_BOT_USERNAME` (без @), `PROD_MODERATORS_CHAT_ID` (K29, `-100…`; пока
   пусто — кейсы решают командами `cli`), `SENTRY_DSN`, `TMA_SENTRY_DSN`.
2. Случайные секреты — как в разделе 2, тем же циклом `make gen-secret` с именами
   `APP_HASH_KEY TELEGRAM_WEBHOOK_SECRET APP_ADMIN_SESSION_KEY`. `APP_HASH_KEY` после первого запуска
   не менять.
3. Ключи JWT — через образ, во временный файл (как на stage):
   ```
   t=$(mktemp -d) && docker run --rm -v "$t:/out" ghcr.io/<владелец>/sosed-backend:main cli jwt-keys --env-file /out/jwt.env \
     && cut -d= -f2- "$t/jwt.env" | gh secret set JWT_KEYS --env production && pbcopy < "$t/jwt.env"; rm -rf "$t"
   ```
4. `gh secret set TELEGRAM_BOT_TOKEN --env production` (K40a), `CLOUDFLARE_API_TOKEN` — токен
   `ci-wrangler` (K12), по желанию `AI_OPENAI_API_KEY`, `AI_ANTHROPIC_API_KEY`. Без `--body` `gh`
   спросит значение скрыто.

Бот на проде принимает апдейты webhook (ADR-0011, 0.25e) на своём хосте:
`https://bot.<домен>/integrations/telegram/webhook` с `secret_token` = `TELEGRAM_WEBHOOK_SECRET`
(`TELEGRAM_UPDATES` и `TELEGRAM_WEBHOOK_BASE_URL` — в `infra/kamal/deploy.production.yml`, маршрут —
роль `bot` в kamal-proxy). Webhook процесс выставляет сам при каждом старте; откат на long polling —
`TELEGRAM_UPDATES: polling` и `proxy: false` у роли `bot` в `deploy.production.yml`, затем деплой.

## 5. Первый релиз (3.1c)

1. Actions → deploy → Run workflow: `env` = `production`, `action` = `accessories` → Approve (Valkey).
2. Затем `action` = `deploy`, `version` = sha коммита main с образом `sosed-backend` → Approve.
   Job: pre-deploy (smoke БД на `db-1` и `alembic upgrade head`), kamal-proxy, web/bot/worker/
   worker-media; следом — сборка Mini App того же sha и `wrangler deploy --env production`.
3. Привязать `app.<домен>`: `mini_app_worker_deployed = true` в `terraform.tfvars`,
   `make tf ENV=prod ARGS='apply'`.
4. Сиды справочников — в контейнере web: `ssh root@<PROD_HOST> 'docker exec $(docker ps -qf label=role=web | head -1) sosed cli seed'`.
   Демо-данных (`seed-demo`) на prod нет.
5. Профиль бота, кнопка меню и webhook (с очередью и последней ошибкой доставки): тем же способом
   `sosed cli bot-setup --env production`.
6. Проверка:
   ```
   curl -s https://api.<домен>/up
   curl -s -o /dev/null -w '%{http_code}\n' -X POST https://bot.<домен>/integrations/telegram/webhook   # 401
   curl -si https://app.<домен>/api/v1/client-config | head -1
   PROD_HOST=<ip> PROD_DB_IP=10.20.1.20 make pg-smoke ENV=prod
   ```
   В Telegram: prod-бот открывает Mini App, ссылка `t.me/<бот>?startapp=h` — Главную.
7. Откат — тот же workflow, `action` = `rollback`, `version` = прошлый sha (история запусков или
   `docker ps -a` на `app-1`). Проверить откат один раз до ворот 3.4 (план 3.1c). Mini App:
   `npx wrangler@4.147.0 rollback` с `--env production` ([release-rollback.md](release-rollback.md)).

## 6. Админка за Access (3.1c)

Нужно: K31 (организация Zero Trust, метод входа One-time PIN), K30 (e-mail персонала; учётки
персонала — `cli staff-create`).

1. В `infra/terraform/prod/terraform.tfvars`: `access_enabled = true`, `access_emails = ["…"]`;
   `make tf ENV=prod ARGS='apply'`.
2. Проверка: `curl -si https://admin.<домен>/admin | grep -i '^location'` — редирект на
   `<team>.cloudflareaccess.com`. `https://api.<домен>/admin` — 403 (правило стека зоны).
3. Variable `production` `PROD_ADMIN_PUBLISHED` = `true` и релиз (`deploy`). Перед выкаткой job сам
   проверяет редирект Access; без него релиз останавливается. kamal-proxy начинает обслуживать
   `admin.<домен>`, web получает `APP_ADMIN_SESSION_KEY` и монтирует `/admin` (2.7a).
4. Учётки персонала: `ssh root@<PROD_HOST> 'docker exec -it $(docker ps -qf label=role=web | head -1) sosed cli staff-create'`
   (пароль и TOTP вводите сами), роли — `sosed cli staff-grant`.

## 7. Бэкапы и restore-тест (3.2)

Нужно: K36 (проект `specialist-backup`: бакет, S3-ключи, токен `restore-test`), K37 (бакет и ключ B2),
K10a (копии), K33 (ping URL «pgBackRest» и «restore-test»), K19. Что и как устроено —
[restore.md](restore.md). Stage бэкапов не получает: там тестовые данные.

1. Пароли шифрования — по одному на репозиторий, как пароли ролей в разделе 2. Копия в менеджере
   паролей обязательна (K10a): без неё бэкап не расшифровать. После первого бэкапа пароль не менять.
   ```
   for n in PGBACKREST_REPO1_CIPHER_PASS PGBACKREST_REPO2_CIPHER_PASS; do
     make gen-secret NAME=$n ENV=production || break
   done
   ```
2. Те же пароли для restore-теста — **из менеджера паролей**, не из буфера генерации: откройте запись,
   скопируйте значение и вставьте в скрытый запрос
   ```
   gh secret set RESTORE_TEST_REPO1_CIPHER_PASS --env production
   gh secret set RESTORE_TEST_REPO2_CIPHER_PASS --env production
   ```
   Зелёный restore-тест с ними — критерий K10a: копия в менеджере верна. Запишите в
   [restore.md](restore.md) («Где что лежит»), где лежат копии.
3. S3-ключи (`gh secret set … --env production`, значение — в скрытый запрос):
   `PGBACKREST_REPO1_S3_KEY`, `PGBACKREST_REPO1_S3_KEY_SECRET` — Hetzner (K36);
   `PGBACKREST_REPO2_S3_KEY`, `PGBACKREST_REPO2_S3_KEY_SECRET` — B2, keyID и applicationKey (K37).
4. Variables environment `production`:
   | Имя | Пример |
   |---|---|
   | `PGBACKREST_REPO1_S3_ENDPOINT` | `nbg1.your-objectstorage.com` |
   | `PGBACKREST_REPO1_S3_REGION` | `nbg1` |
   | `PGBACKREST_REPO1_S3_BUCKET` | имя бакета из K36 |
   | `PGBACKREST_REPO2_S3_ENDPOINT` | `s3.eu-central-003.backblazeb2.com` (из настроек бакета B2) |
   | `PGBACKREST_REPO2_S3_REGION` | `eu-central-003` |
   | `PGBACKREST_REPO2_S3_BUCKET` | имя бакета из K37 |

   Без `PGBACKREST_REPO2_*` бэкапы идут только в Hetzner; B2 можно добавить позже тем же
   `db-provision`.
5. Healthchecks (K33): проверка «pgBackRest» — период 1 день, grace 3 часа; «restore-test» — период
   31 день, grace 3 дня (запуск ждёт вашего подтверждения). Ping URL — секреты
   `PGBACKREST_HEALTHCHECK_URL` и `RESTORE_TEST_HEALTHCHECK_URL`.
6. Токен `restore-test` проекта `specialist-backup` (K36) — секрет `HCLOUD_TOKEN` в `production`.
   Это не prod-токен (K38): restore-тест создаёт VM только в `specialist-backup`.
7. Включить: Actions → deploy → Run workflow, `env` = `production`, `action` = `db-provision` →
   Approve. В логе: стенза `specialist`, `check` зелёный, таймер бэкапов и «первый запущен в фоне».
   Проверка:
   ```
   ssh -J root@<PROD_HOST> root@10.20.1.20 'systemctl list-timers sosed-pgbackrest-backup.timer; sudo -u postgres pgbackrest --stanza=specialist info'
   ```
   С этого момента `db-provision` без ключей pgBackRest падает намеренно: иначе он выключил бы архив WAL.
8. Restore-тест: Variable репозитория `RESTORE_TEST` = `true`, затем после первого бэкапа
   ```
   gh workflow run restore-test.yml -f repo=1
   gh workflow run restore-test.yml -f repo=2
   ```
   → Approve. Оба зелёные — числа RPO и RTO из Summary в таблицу [restore.md](restore.md). Дальше тест
   идёт сам 3-го числа каждого месяца, по очереди по репозиториям.

## 8. Наблюдаемость (3.3)

Нужно: K35 (Grafana Cloud), K33 (Healthchecks), K34 (UptimeRobot), K35a (канал алертов), K20 (Sentry).
Как устроено: `infra/monitoring/alloy` — Grafana Alloy (accessory `alloy` только на `app-1`: метрики
ролей с порта 9091, хост, PostgreSQL db-1 ролью `monitoring` по приватной сети, node exporter db-1, логи
ролей в Loki с маскированием); `infra/monitoring/rules` — алерты; `infra/monitoring/dashboards` —
дашборды; `infra/terraform/monitoring` — UptimeRobot. Бюджет Grafana Cloud Free — 10k активных рядов
на оба окружения: ряды экспортёров проходят по спискам «оставить» в `config.alloy`.

1. Grafana Cloud (K35). Variables репозитория (стек один на stage и prod, окружение — метка `env`):
   `GRAFANA_CLOUD_PROM_URL` (адрес remote_write, `https://prometheus-….grafana.net/api/prom/push`),
   `GRAFANA_CLOUD_PROM_USER`, `GRAFANA_CLOUD_LOKI_URL` (`https://logs-….grafana.net/loki/api/v1/push`),
   `GRAFANA_CLOUD_LOKI_USER`. Секрет — токен access policy с `metrics:write` и `logs:write`:
   `make secret NAME=GRAFANA_CLOUD_TOKEN TARGET=production`. Пока `GRAFANA_CLOUD_PROM_URL` пуст,
   accessory `alloy` в конфиге Kamal нет вовсе.
2. Роль `monitoring` (только `pg_monitor`, данных таблиц не видит):
   `make gen-secret NAME=MONITORING_DB_PASSWORD ENV=production`, затем `db-provision` (раздел 2):
   роль получит пароль, `pg_hba` пустит её из подсети prod, на `db-1` встанет `prometheus-node-exporter`
   из пакетов Ubuntu (слушает только адрес приватной сети, порт 9100 ufw открывает только подсети).
3. Heartbeat воркера (K33): в Healthchecks проверка «worker prod» — Simple, период 1 минута, grace
   5 минут; ping URL — `make secret NAME=HEALTHCHECKS_WORKER_PING_URL TARGET=production` (только роль
   `worker`). Проверки «pgBackRest» и «restore-test» — раздел 7. Integrations — e-mail (K35a), по желанию
   Telegram alert-бот.
4. Actions → deploy → `env` = `production`, `action` = `accessories` → Approve: Kamal пропускает
   работающий Valkey и поднимает `alloy`; затем `deploy` — роли получат `METRICS_PORT` и ping URL.
   Новая версия конфига или образа Alloy — `make kamal ARGS='accessory reboot alloy -d production'`.
   Проверка: `ssh root@<PROD_HOST> 'docker logs --tail 30 sosed-alloy'` — без `error`; через пару
   минут в Grafana → Explore → Prometheus: `up{env="production"}` — роли (`job="sosed"`), `node`
   (`app-1`, `db-1`) и `postgres`, у всех 1.
5. Алерты и дашборды как код — ключи в `infra/monitoring/.env` (`make secret NAME=… TARGET=monitoring`):
   `MIMIR_ADDRESS` (адрес Prometheus стека без пути, `https://prometheus-….grafana.net`),
   `MIMIR_TENANT_ID` (user id Prometheus), `MIMIR_API_KEY` (отдельный токен access policy с
   `rules:read` и `rules:write` — у серверов его нет), `GRAFANA_URL` (`https://<стек>.grafana.net`),
   `GRAFANA_SA_TOKEN` (service account с ролью Editor, K35 шаг 3). Затем
   ```
   make monitoring-check                  # без ключей: alloy validate, promtool check и test
   make monitoring-rules                  # diff: что изменится в ruler
   make monitoring-rules APPLY=1          # mimirtool rules sync, пространство имён sosed
   make monitoring-dashboards APPLY=1     # папка «Соседи»: API RED, очереди и Telegram, хост и PostgreSQL
   ```
   Правки в UI перезаписываются следующим запуском: источник — файлы в git.
6. Канал алертов (K35a). Алерты правил ruler приходят в Alertmanager стека: Alerting → Contact points →
   в списке Alertmanager — тот, что указан у правил `sosed` (Alerting → Alert rules) → контакт e-mail
   владельца (по умолчанию), по желанию Telegram alert-бот; Notification policies: по умолчанию — этот
   контакт, `env=stage` — тот же контакт с `repeat_interval` 12 h (или mute timing, если stage выключен).
7. UptimeRobot (K34): `make secret NAME=UPTIMEROBOT_API_KEY TARGET=tf-monitoring`,
   `cp infra/terraform/monitoring/monitoring.tfvars.example infra/terraform/monitoring/monitoring.auto.tfvars`
   (домен, e-mail для алертов; файл в git не попадает), `prod_enabled = true` после первого релиза, затем
   `make tf ENV=monitoring ARGS='init'`, `ARGS='plan'`, `ARGS='apply'`. Мониторы: `api.` и `bot.` `/up`,
   Mini App `app.`, раз в 5 минут; то же для stage. Копию `terraform.tfstate` — в менеджер паролей.
8. Тестовый алерт доходит:
   - Grafana: Contact points → контакт → Test — письмо пришло;
   - Healthchecks: на stage `make kamal ARGS='app stop --roles=worker -d stage'` — через ≈ 6 минут
     письмо «worker stage is DOWN», затем `make kamal ARGS='app start --roles=worker -d stage'` (Проверка 3.3);
   - ruler целиком: `make kamal ARGS='accessory stop alloy -d stage'` — через 30 минут
     `SosedMetricsMissing` (env=stage) в почте, затем `accessory start alloy -d stage`;
   - UptimeRobot: монитор → Pause/Resume не шлёт алерт — проверять остановкой `bot` на stage
     (`app stop --roles=bot`, через 5–10 минут письмо о мониторе «stage: бот /up», затем `app start`).
9. Loki без ПД — выборочно раз в релиз и в 8.2: Explore → Loki за сутки
   ```
   {env="production"} |~ "\\+381|\\+7[0-9]|@[A-Za-z0-9-]+\\.[a-z]|eyJ[A-Za-z0-9_-]{8,}\\.|user=%7B|query_id="
   ```
   — пусто (маскирование первого рубежа — `platform/observability/masking.py`, второго — `config.alloy`);
   и 50 строк `{env="production", role="web"}` глазами: нет имён, телефонов, адресов и текстов
   сообщений. Логи PostgreSQL (тексты медленных запросов с литералами) и kamal-proxy (IP и User-Agent)
   в Loki не уходят вовсе. Дату и итог — в «Сделано» шага 3.3.
10. Рядов не больше бюджета: Grafana Cloud → Usage → Metrics — активных рядов на оба окружения
    ≈ 3–5k при 10k бесплатных. Рост — сначала `topk(10, count by (__name__) ({__name__=~".+"}))`.

## Ключи SSH и доступ к db-1

Terraform кладёт ключи на обе VM только при создании (`ignore_changes`). Новый ключ на живую VM —
`ssh root@<PROD_HOST> 'cat >> ~/.ssh/authorized_keys' < новый.pub` и так же через `-J` на `db-1`;
отзыв — удалить строку там же; в `terraform.tfvars` поправить список, чтобы пересозданная VM получила
те же ключи. Если `app-1` недоступен, на `db-1` — только консоль Hetzner (rescue).

Удаление и пересборка VM защищены (`delete_protection`, `prevent_destroy` у `db-1`): снять защиту —
отдельной правкой в `infra/terraform/prod/hetzner.tf`, по решению владельца.
