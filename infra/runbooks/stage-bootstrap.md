# Подъём stage с нуля

Порядок действий владельца и команды, после которых stage работает: VM в Hetzner (0.25a), Cloudflare
(0.25b), backend и БД через Kamal (0.25c), Mini App на Workers (0.25d), stage-бот (0.25e).
Код окружения — `infra/terraform/stage`, `infra/kamal`, `infra/workers/tma`,
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
3. Сертификат Origin CA для kamal-proxy — сразу в секреты, минуя экран (`< /dev/null` — без TTY,
   иначе в PEM попадут `\r`):
   ```
   make tf ENV=stage ARGS='output -raw origin_certificate_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_CERT --env stage
   make tf ENV=stage ARGS='output -raw origin_private_key_pem' < /dev/null | gh secret set KAMAL_PROXY_SSL_KEY --env stage
   ```
4. Variables environment `stage`: `STAGE_DOMAIN` (домен), `CLOUDFLARE_ACCOUNT_ID`.
5. Проверка: `dig +short stage-api.<домен>` — адреса Cloudflare, не VM; повторный `plan` — «No changes».

Создаётся: A/AAAA `stage-api.` и A `stage-admin.` (прокси Cloudflare на VM), бакеты
`sosed-stage-incoming|media|private` в EU (CORS для `https://stage-app.<домен>`, `ETag` наружу;
incoming живёт 2 дня, незавершённые multipart — сутки), `stage-cdn.` → бакет media, skip-правило WAF
для webhook Telegram (`/integrations/telegram/` с адресов Bot API), SSL Full (strict), HTTPS
always, TLS ≥ 1.2. `stage-admin.` ничего не отдаёт до Access (K31, 2.7b): kamal-proxy этот хост не
обслуживает, а web без `APP_ADMIN_SESSION_KEY` не монтирует `/admin`.

## 3. Backend и БД через Kamal (0.25c)

Нужно: Q1, K13 (S3-ключи R2 только на три бакета stage), K15, K16 (PAT не нужен: CI логинится в
GHCR своим `GITHUB_TOKEN`), K17 (токен бота — для старта процессов), K19, K10a, K20 (DSN — по
желанию).

1. Variables environment `stage`: `STAGE_BOT_USERNAME` (без @), `SENTRY_DSN` (backend),
   `TMA_SENTRY_DSN` (Mini App) — DSN можно оставить пустыми.
2. Секреты environment `stage` (имена — `infra/kamal/secrets.stage`). Случайные значения — в своём
   Терминале, без вывода на экран: значение уходит в буфер обмена (вставить в менеджер паролей) и в
   GitHub. `make gen-secret` (0.25c) пока не написан — до него так:
   ```
   for n in POSTGRES_SUPERUSER_PASSWORD APP_DB_PASSWORD MIGRATOR_DB_PASSWORD READONLY_DB_PASSWORD \
            BACKUP_DB_PASSWORD APP_HASH_KEY TELEGRAM_WEBHOOK_SECRET; do
     v=$(openssl rand -hex 32); printf %s "$v" | pbcopy; printf %s "$v" | gh secret set "$n" --env stage
     printf '%s: вставьте из буфера в менеджер паролей и нажмите Enter ' "$n"; read -r _
   done; unset v; printf x | pbcopy
   ```
   Пароли — только hex: они входят в DSN (`postgresql+psycopg://app:<пароль>@sosed-postgres/…`).
   `APP_HASH_KEY` после первого запуска не менять (хэши удалённых аккаунтов «забудутся»).
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
6. Actions → deploy-stage → Run workflow: сначала `accessories` (первый старт PostgreSQL на пустом
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
   история запусков deploy-stage).
8. Сиды после первого деплоя (в контейнере web; Kamal метит контейнеры `role=web`):
   `ssh root@<STAGE_HOST> 'docker exec $(docker ps -qf label=role=web | head -1) sosed cli seed'`,
   затем так же `sosed cli seed-demo --scale small` (2.8c).

Секреты stage локально у вас не лежат (Q1(б)), поэтому деплой и откат — через CI; `make kamal
ARGS='… -d stage'` — для команд, которым секреты не нужны (логи, `app details`), или со значениями из
менеджера паролей в окружении (Q15).

## 4. Mini App на Workers (0.25d)

Нужно: K12 (токен `ci-wrangler`: Workers Scripts Edit, Account Settings Read).

1. `gh secret set CLOUDFLARE_API_TOKEN --env stage` — токен `ci-wrangler`.
2. Первый деплой Worker'а — тот же deploy-stage (`deploy`) или любой merge фронтенда: job «Mini App»
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

Сейчас процесс `bot` на stage принимает апдейты long polling: webhook-режима (`setWebhook` с
`secret_token` и узким `allowed_updates`, приём на `/integrations/telegram/webhook`) в коде ещё нет —
это часть 0.25e. Край к нему готов: skip-правило WAF и `TELEGRAM_WEBHOOK_SECRET` в секретах.

Профиль бота и кнопка меню — существующей командой, в контейнере web на VM:
```
ssh root@<STAGE_HOST> 'docker exec $(docker ps -qf label=role=web | head -1) sosed cli bot-setup --env stage'
```
Проверка: вход в Mini App из stage-бота на телефоне.

## Ключи SSH

Terraform кладёт ключи на VM только при создании (`ignore_changes`). Новый ключ на живую VM —
`ssh root@<STAGE_HOST> 'cat >> ~/.ssh/authorized_keys' < новый.pub`, отзыв — удалить строку там же; в
`terraform.tfvars` поправить список, чтобы пересозданная VM получила те же ключи.
