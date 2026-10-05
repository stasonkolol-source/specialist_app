# Подъём stage с нуля

Порядок действий владельца и команды, после которых stage работает: VM в Hetzner (0.25a), Cloudflare
(0.25b), backend и БД через Kamal (0.25c), Mini App на Workers (0.25d), stage-бот (0.25e).
Код окружения — `infra/terraform/stage` (и общий для зоны `infra/terraform/zone`), `infra/kamal`, `infra/workers/tma`,
`.github/workflows/deploy.yml`. Пункты K и Q — [OWNER_CHECKLIST](../../docs/OWNER_CHECKLIST.md).

> Прогон «на сухую» — при первом подъёме stage (ключи K11–K17). Ни одна команда ниже до этого не
> запускалась против Hetzner и Cloudflare: проверены только `terraform validate`, план без сети и
> `kamal config` на фиктивных значениях (2026-10-04).

Правила для всего runbook:
- все команды — в своём окне Терминала из `~/PycharmProjects/specialist_app`, не в чате;
- секрет — в менеджер паролей (K10a) **в момент создания**, потом в `.env` или GitHub;
- `terraform output` с ключами и `gh secret set --body` не используем: значение — только трубой.

## 0. До начала

| Что | Пункт | По умолчанию |
|---|---|---|
| Менеджер паролей, 2FA, папка `specialist-stage` | K10, K10a, Q15 | — |
| Где хранить секреты stage | Q1 | (б) секреты GitHub environment `stage`; репозиторий публичный, environments доступны |
| GitHub environment `stage`: Settings → Environments → New → `stage` → Deployment branches → Selected → `main` | K19, Q5 | — |
| `brew install gh`, `gh auth login` | K3 | — |

## 1. VM в Hetzner (0.25a)

Нужно: K14 (проект `specialist-stage`, токен), K15 (ваш публичный ключ), Q12 (регион, по умолчанию
`nbg1`), Q13 (SSH: по умолчанию 22-й порт открыт, вход только по ключу — иначе не сможет деплоить CI),
Q14 (state: по умолчанию локальный, в git не попадает), Q16.

1. Токен: `make secret NAME=HCLOUD_TOKEN TARGET=tf-stage`.
2. Deploy-ключ stage для CI (K15, отдельный от prod), без пароля — его держит только ssh-agent CI:
   ```
   ssh-keygen -t ed25519 -N '' -C deploy-stage -f ~/.ssh/sosed_stage_deploy
   gh secret set DEPLOY_SSH_KEY --env stage < ~/.ssh/sosed_stage_deploy
   ```
   Приватную часть — в менеджер паролей (`pbcopy < ~/.ssh/sosed_stage_deploy`, вставить, скопировать
   что-нибудь другое), затем `rm ~/.ssh/sosed_stage_deploy`.
3. `cp infra/terraform/stage/stage.tfvars.example infra/terraform/stage/terraform.tfvars` и вписать
   `ssh_public_keys`: ваш `~/.ssh/id_ed25519.pub` и `~/.ssh/sosed_stage_deploy.pub`. Секретов в этом
   файле нет, его можно коммитить.
4. ```
   make tf ENV=stage ARGS='init'
   make tf ENV=stage ARGS='plan'
   make tf ENV=stage ARGS='apply'
   make tf ENV=stage ARGS='output stage_ipv4'
   ```
   IPv4 — переменная `STAGE_HOST` environment `stage` (Settings → Environments → stage → Variables).
5. Проверка (≈ 3 минуты на cloud-init):
   ```
   ssh root@<STAGE_HOST> 'cloud-init status --wait && docker network inspect kamal -f "{{(index .IPAM.Config 0).Subnet}}"'
   ```
   Ждём `status: done` и `172.30.0.0/24` (эту подсеть web считает своим прокси — `APP_TRUSTED_PROXIES`).
6. Копию `infra/terraform/stage/terraform.tfstate` — в менеджер паролей после каждого `apply` (Q14).
7. Готово, когда повторный `make tf ENV=stage ARGS='plan'` пишет «No changes».

## 2. Cloudflare: DNS, R2, WAF, SSL (0.25b)

Нужно: K11 (домен в Cloudflare, Account ID и Zone ID — Overview домена), K12 (токен `terraform`),
K13 (включить R2), Q9 (домен; хватит технического), Q10 (плоская схема `stage-*.`).

1. `make secret NAME=CLOUDFLARE_API_TOKEN TARGET=tf-stage`.
2. В `terraform.tfvars`: `cloudflare_enabled = true`, `domain`, `cloudflare_account_id`,
   `cloudflare_zone_id`. Затем `make tf ENV=stage ARGS='plan'` и `ARGS='apply'`.
3. Общий стек зоны (один на stage и prod: Full strict, HTTPS, TLS ≥ 1.2, custom rules WAF):
   ```
   make secret NAME=CLOUDFLARE_API_TOKEN TARGET=tf-zone
   cp infra/terraform/zone/zone.tfvars.example infra/terraform/zone/terraform.tfvars   # domain, cloudflare_zone_id
   make tf ENV=zone ARGS='init' && make tf ENV=zone ARGS='apply'
   ```
4. Сертификат Origin CA для kamal-proxy — сразу в секреты, минуя экран (`< /dev/null` — без TTY,
   иначе в PEM попадут `\r`):
   ```
   make tf ENV=stage ARGS='output -raw origin_certificate_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_CERT --env stage
   make tf ENV=stage ARGS='output -raw origin_private_key_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_KEY --env stage
   ```
5. Variables environment `stage`: `STAGE_DOMAIN` (домен), `CLOUDFLARE_ACCOUNT_ID`.
6. Проверка: `dig +short stage-api.<домен>` и `dig +short stage-bot.<домен>` — адреса Cloudflare,
   не VM; повторный `plan` — «No changes».

Создаётся: A/AAAA `stage-api.` (API) и `stage-bot.` (webhook бота: у роли `bot` свой хост в
kamal-proxy — Kamal не даёт двум ролям один хост с TLS), A `stage-admin.` — всё через прокси
Cloudflare на VM, все три имени — в сертификате Origin CA; бакеты `sosed-stage-incoming|media|private`
в EU (CORS для `https://stage-app.<домен>`, `ETag` наружу; incoming живёт 2 дня, незавершённые
multipart — сутки), `stage-cdn.` → бакет media. В стеке зоны `infra/terraform/zone`: skip-правило
WAF для webhook Telegram (`/integrations/telegram/` на `stage-bot.` и `bot.` с адресов Bot API),
запрет `/admin` на хостах API, SSL Full (strict), HTTPS always, TLS ≥ 1.2. `stage-admin.` ничего не
отдаёт до Access (K31, 2.7b): kamal-proxy этот хост не обслуживает, а web без
`APP_ADMIN_SESSION_KEY` не монтирует `/admin`. Когда stage-админку откроют за Access, вместе с ключом
сессии заводится `APP_TOTP_KEY` (`make gen-secret`, как на проде — `prod-bootstrap.md`, раздел 4):
с ключом сессии, но без ключа шифрования секретов TOTP персонала (8.4) процессы не стартуют.

## 3. Backend и БД через Kamal (0.25c)

Нужно: Q1, K13 (S3-ключи R2 только на три бакета stage), K15, K16 (PAT не нужен: CI логинится в
GHCR своим `GITHUB_TOKEN`), K17 (токен бота — для старта процессов), K19, K10a, K20 (DSN — по
желанию).

1. Variables environment `stage`: `STAGE_BOT_USERNAME` (без @), `SENTRY_DSN` (backend),
   `TMA_SENTRY_DSN` (Mini App) — DSN можно оставить пустыми. Source maps Mini App в Sentry (K20, по
   желанию): секрет репозитория `SENTRY_AUTH_TOKEN` (organization token) и Variables репозитория
   `SENTRY_ORG`, `TMA_SENTRY_PROJECT`; без них шаг деплоя «Sentry source maps» пропускается с notice.
2. Секреты environment `stage` (имена — `infra/kamal/secrets.stage`). Случайные значения — в своём
   Терминале командой `make gen-secret`: значение (32 байта в hex) показывается один раз и уже лежит
   в буфере обмена — вставьте его в менеджер паролей (K10a) и нажмите Enter; скрипт передаст его в
   GitHub (`gh secret set --env stage`, через stdin) и сотрёт экран и буфер. Ctrl+C до Enter — в
   GitHub ничего не уходит.
   ```
   for n in POSTGRES_SUPERUSER_PASSWORD APP_DB_PASSWORD MIGRATOR_DB_PASSWORD READONLY_DB_PASSWORD \
            BACKUP_DB_PASSWORD APP_HASH_KEY TELEGRAM_WEBHOOK_SECRET; do
     make gen-secret NAME=$n ENV=stage || break
   done
   ```
   Пароли — только hex: они входят в DSN (`postgresql+psycopg://app:<пароль>@sosed-postgres/…`).
   `APP_HASH_KEY` после первого запуска не менять (хэши удалённых аккаунтов «забудутся»).
   `TELEGRAM_WEBHOOK_SECRET` — `secret_token` webhook бота (шаг 5). Своё значение (например, из
   менеджера паролей после пересоздания environment) — `make secret NAME=… TARGET=stage`.
3. Ключи JWT (формат `cli jwt-keys`) — через образ, во временный файл:
   ```
   t=$(mktemp -d) && docker run --rm -v "$t:/out" ghcr.io/<владелец>/sosed-backend:main cli jwt-keys --env-file /out/jwt.env \
     && cut -d= -f2- "$t/jwt.env" | gh secret set JWT_KEYS --env stage && pbcopy < "$t/jwt.env"; rm -rf "$t"
   ```
4. Внешние ключи: `gh secret set TELEGRAM_BOT_TOKEN --env stage` (K17), `S3_ACCESS_KEY_ID` и
   `S3_SECRET_ACCESS_KEY` (K13), по желанию `AI_OPENAI_API_KEY`, `AI_ANTHROPIC_API_KEY` (K25, K26;
   без них всё идёт в ручную очередь). `gh secret set ИМЯ --env stage` без `--body` спросит значение
   скрыто.
5. Variable репозитория (Settings → Secrets and variables → Actions → Variables) `STAGE_DEPLOY` =
   `true` — с этого момента `.github/workflows/deploy.yml` работает.
6. Actions → deploy → Run workflow (`env` = `stage`): сначала `accessories` (первый старт PostgreSQL на пустом
   томе: initdb и `bootstrap.sql` — роли и расширения, как в dev; Valkey), затем `deploy` с `version` =
   sha последнего коммита main, у которого есть образ `sosed-backend` (Packages репозитория).
   Деплой: pre-deploy (smoke БД и `alembic upgrade head`), kamal-proxy, web/bot/worker/worker-media.
7. Проверка:
   ```
   curl -s https://stage-api.<домен>/up
   STAGE_HOST=<ip> make pg-smoke ENV=stage
   ssh root@<STAGE_HOST> docker ps --format '{{.Names}} {{.Status}}'
   ```
   `kamal rollback` — тот же workflow, `rollback` и прошлый sha (список — `docker ps -a` на VM или
   история запусков deploy).
8. Сиды после первого деплоя (в контейнере web; Kamal метит контейнеры `role=web`):
   `ssh root@<STAGE_HOST> 'docker exec $(docker ps -qf label=role=web | head -1) sosed cli seed'`,
   затем так же `sosed cli seed-demo --scale small` (2.8c).

Секреты stage локально у вас не лежат (Q1(б)), поэтому деплой и откат — через CI; `make kamal
ARGS='… -d stage'` — для команд, которым секреты не нужны (логи, `app details`), или со значениями из
менеджера паролей в окружении (Q15).

## 4. Mini App на Workers (0.25d)

Нужно: K12 (токен `ci-wrangler`: Workers Scripts Edit, Account Settings Read).

1. `gh secret set CLOUDFLARE_API_TOKEN --env stage` — токен `ci-wrangler`.
2. Первый деплой Worker'а — тот же deploy (`env` = `stage`, `deploy`) или любой merge фронтенда: job «Mini App»
   собирает `apps/tma` с `VITE_*` из Variables и выполняет
   `npx wrangler@4.147.0 deploy --config infra/workers/tma/wrangler.jsonc --env stage --var API_ORIGIN:https://stage-api.<домен>`.
3. Привязать домен: в `terraform.tfvars` `mini_app_worker_deployed = true`,
   `make tf ENV=stage ARGS='apply'` — Terraform создаёт `stage-app.<домен>` на Worker `sosed-tma-stage`.
4. Проверка: `curl -si https://stage-app.<домен>/api/v1/nope` — problem+json от API через прокси;
   `https://stage-app.<домен>` открывается.

Откат Mini App: `npx wrangler@4.147.0 deployments list --config infra/workers/tma/wrangler.jsonc --env stage`,
затем `npx wrangler@4.147.0 rollback <id> …` с теми же ключами (токен — в окружении `CLOUDFLARE_API_TOKEN`).

## 5. Stage-бот (0.25e)

Нужно: K17 (бот «Соседи stage», Main Mini App на `https://stage-app.<домен>`), Q11 (по умолчанию —
основная среда Telegram).

Процесс `bot` принимает апдейты webhook (`TELEGRAM_UPDATES: webhook` в `infra/kamal/deploy.stage.yml`)
на своём хосте: `https://stage-bot.<домен>/integrations/telegram/webhook` (`TELEGRAM_WEBHOOK_BASE_URL`).
Запись и сертификат — Terraform stage (шаг 2), skip-правило WAF — стек зоны, маршрут — роль `bot` в
kamal-proxy. Webhook с `secret_token` = `TELEGRAM_WEBHOOK_SECRET` (шаг 3) и узким `allowed_updates`
процесс выставляет сам при каждом старте, то есть при каждом деплое; запрос без секрета или с чужим
получает 401 и не обрабатывается.

Профиль бота, кнопка меню и тот же webhook — с очередью и последней ошибкой доставки из
`getWebhookInfo` — командой в контейнере web на VM:
```
ssh root@<STAGE_HOST> 'docker exec $(docker ps -qf label=role=web | head -1) sosed cli bot-setup --env stage'
```
Проверка:
```
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://stage-bot.<домен>/integrations/telegram/webhook   # 401
```
и вход в Mini App из stage-бота на телефоне. `last error` в выводе `bot-setup` — смотреть логи роли:
`ssh root@<STAGE_HOST> 'docker logs --tail 50 $(docker ps -qf label=role=bot | head -1)'`. Откат на
long polling — в `deploy.stage.yml` `TELEGRAM_UPDATES: polling` и `proxy: false` у роли `bot` (polling
не отвечает на `/up`, и kamal-proxy не дождался бы healthcheck), затем деплой: процесс сам снимет
webhook.

## 6. Наблюдаемость (3.3)

Нужно: K35 (Grafana Cloud), K33 (Healthchecks); по желанию K34 (UptimeRobot). То же, что на prod
([prod-bootstrap.md](prod-bootstrap.md), раздел 8), но Alloy — на той же VM, PostgreSQL — accessory
`sosed-postgres` в сети `kamal`, а алерты stage идут с меткой `env=stage`.

1. Variables репозитория `GRAFANA_CLOUD_*` и секрет `GRAFANA_CLOUD_TOKEN` (`TARGET=stage`) — как в
   prod-bootstrap.md, раздел 8, шаг 1.
2. `make gen-secret NAME=MONITORING_DB_PASSWORD ENV=stage`. Новый stage (пустой том) получит роль в
   initdb. Существующей БД роль даёт сам `bootstrap.sql`: пересоздать accessory с новым секретом и
   применить его заново (идемпотентно; PostgreSQL перезапустится — на stage это секунды):
   ```
   make kamal ARGS='accessory reboot postgres -d stage'
   ssh root@<STAGE_HOST> 'docker exec sosed-postgres bash /docker-entrypoint-initdb.d/10-bootstrap.sh'
   ```
   (`make kamal` берёт значения из окружения — как при подъёме stage, раздел 3.)
3. Healthchecks: проверка «worker stage» — период 1 минута, grace 5 минут;
   `make secret NAME=HEALTHCHECKS_WORKER_PING_URL TARGET=stage`.
4. Actions → deploy → `env` = `stage`, `action` = `accessories` (поднимет `alloy`), затем `deploy`.
   Проверка: `ssh root@<STAGE_HOST> 'docker logs --tail 30 sosed-alloy'` без `error`; в Grafana →
   Explore: `up{env="stage"}` — роли, `node` (`stage`) и `postgres`, у всех 1.
5. Алерты, дашборды, UptimeRobot и проверки «тестовый алерт доходит» и «Loki без ПД» — шаги 5–9
   раздела 8 prod-bootstrap.md (`stage_enabled = true` в `monitoring.auto.tfvars`).

## 7. Карта выбора точки (Q28)

Нужно: раздел 2 (бакет `sosed-stage-media` и домен `stage-cdn.`), K13 (S3-ключи R2 stage), Docker и
git на Маке. Тайлы Нови-Сада, шрифты и спрайт лежат в бакете media под `map/<версия>/` и отдаются
с `stage-cdn.` — с HTTP Range, которого требует PMTiles (статика Workers его не умеет). Подробно —
[scripts/map/README.md](../../scripts/map/README.md). Пока Variable нет, Mini App собирается без
карты (список районов).

1. Загрузка — в своём Терминале; ключи K13 из менеджера паролей вводятся скрыто и живут только в
   этом окне:
   ```
   read -rs S3_ACCESS_KEY_ID && read -rs S3_SECRET_ACCESS_KEY && export S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
   R2_ACCOUNT_ID=<Account ID> make map-upload ENV=stage
   ```
   Команда соберёт ассеты в `apps/tma/public/map`, если их ещё нет (как `make map-assets`, ~1 минута),
   и напечатает версию.
   Повтор безопасен: одинаковые файлы пропускаются, другое содержимое под той же версией не
   перезаписывается.
2. Проверка — GET первых 100 байт (ждём `206`, `content-range: bytes 0-99/…` и
   `access-control-allow-origin` с адресом Mini App):
   ```
   curl -s -o /dev/null -D - -r 0-99 -H 'Origin: https://stage-app.<домен>' https://stage-cdn.<домен>/map/<версия>/novi-sad.pmtiles
   ```
3. Variable environment `stage` `MAP_ASSETS_VERSION` = версия из вывода (например `20260811`), затем
   deploy (`env` = `stage`, `deploy`) или любой merge фронтенда: сборка получит
   `VITE_MAP_ASSETS_URL=https://stage-cdn.<домен>/map/<версия>`, а CSP — этот origin в `connect-src`.
4. Новая карта — новая версия: `scripts/map/README.md`, «Новая сборка Protomaps».

## Ключи SSH

Terraform кладёт ключи на VM только при создании (`ignore_changes`). Новый ключ на живую VM —
`ssh root@<STAGE_HOST> 'cat >> ~/.ssh/authorized_keys' < новый.pub`, отзыв — удалить строку там же; в
`terraform.tfvars` поправить список, чтобы пересозданная VM получила те же ключи.
