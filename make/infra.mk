# Stage и prod как код (DEVELOPMENT_PLAN 0.25a–0.25e, 3.1a–3.1c). Подключается из Makefile: -include make/*.mk.
# Terraform и Kamal — только в официальных образах закреплённых версий: ставить их на Мак не нужно,
# у владельца и в CI одна и та же версия. Порядок действий — infra/runbooks/stage-bootstrap.md и
# prod-bootstrap.md.
.PHONY: tf tf-check kamal db-provision

TF_IMAGE ?= hashicorp/terraform:1.16.5@sha256:c7926feace05d0f7e73542842bf3945924e955a1f782cf000ccbb8d18fa42d77
KAMAL_IMAGE ?= ghcr.io/basecamp/kamal:v2.12.0@sha256:7b5be276aa17bbe122887f6a1ff12865f4848111989699b9786083be95d98415
# -t только в терминале: в CI и в трубе его нет
TTY = $$([ -t 0 ] && echo -t)

# Монтируется весь infra/terraform: стеки окружений берут общие модули из ../modules.
tf: ## Terraform стека в Docker: make tf ENV=stage|prod|zone ARGS='plan' (токены — infra/terraform/<стек>/.env)
	@test -n "$(ENV)" && test -n "$(ARGS)" || (echo "usage: make tf ENV=stage|prod|zone ARGS='init|plan|apply|output …'"; exit 2)
	@test -f infra/terraform/$(ENV)/.env || (echo "tf: нет infra/terraform/$(ENV)/.env — make secret NAME=… TARGET=tf-$(ENV)"; exit 2)
	@docker run --rm -i $(TTY) -v "$(ROOT)/infra/terraform:/work" -w /work/$(ENV) \
	  --env-file infra/terraform/$(ENV)/.env $(TF_IMAGE) $(ARGS)

tf-check: ## Terraform без ключей: fmt и validate всех стеков (stage, prod, zone; модули — через них)
	@docker run --rm -v "$(ROOT)/infra/terraform:/work" -w /work --entrypoint terraform $(TF_IMAGE) fmt -check -recursive
	@for dir in $(filter-out infra/terraform/modules/,$(wildcard infra/terraform/*/)); do \
	  echo "tf-check: $$dir"; \
	  docker run --rm -v "$(ROOT)/infra/terraform:/work" -w "/work/$$(basename $$dir)" --entrypoint sh $(TF_IMAGE) -c \
	    'terraform init -backend=false -input=false >/dev/null && terraform validate' || exit 1; \
	done

# Переменные, которые Kamal берёт из окружения: несекретные (адреса VM, домен, владелец образов) и
# имена секретов из infra/kamal/secrets.stage и secrets.production. Значения в команду не попадают:
# docker run -e ИМЯ передаёт переменную из окружения как есть, а задаёт их владелец (менеджер паролей,
# Q15) или CI.
KAMAL_ENV = STAGE_HOST STAGE_DOMAIN STAGE_BOT_USERNAME PROD_HOST PROD_DB_IP PROD_DOMAIN PROD_BOT_USERNAME \
  PROD_MODERATORS_CHAT_ID ADMIN_HOST GHCR_OWNER R2_ACCOUNT_ID SENTRY_DSN APP_RELEASE KAMAL_REGISTRY_USERNAME \
  $(shell sed -n 's/^\([A-Z][A-Z0-9_]*\)=\$$\1$$/\1/p' infra/kamal/secrets.stage infra/kamal/secrets.production 2>/dev/null | sort -u)

# ssh — через агент Docker Desktop (ssh-add ~/.ssh/id_ed25519 на Маке); образ backend Kamal не
# собирает, а скачивает на сервере (--skip-push), поэтому сокет Docker в контейнер не нужен.
kamal: ## Kamal в Docker: make kamal ARGS='deploy -d stage' (STAGE_*/PROD_*, домен, … — из окружения)
	@test -n "$(ARGS)" || (echo "usage: make kamal ARGS='config -d stage'"; exit 2)
	@docker run --rm -i $(TTY) -v "$(ROOT):/workdir" -w /workdir \
	  -v /run/host-services/ssh-auth.sock:/run/host-services/ssh-auth.sock \
	  -e SSH_AUTH_SOCK=/run/host-services/ssh-auth.sock \
	  $(foreach v,$(KAMAL_ENV),-e $(v)) $(KAMAL_IMAGE) $(ARGS) -c infra/kamal/deploy.yml

# --- prod: PostgreSQL на db-1 (3.1b) ---
# У db-1 нет публичного SSH: вход через app-1. ProxyCommand, а не -J: опции командной строки -J к
# прыжку не применяет. PROD_HOST (IPv4 app-1) и PROD_DB_IP (db-1 в приватной сети) — из окружения:
# make tf ENV=prod ARGS='output app_ipv4' и 'output db_private_ip'.
PROD_SSH_OPTS = -o BatchMode=yes -o StrictHostKeyChecking=accept-new
PROD_DB_SSH = ssh $(PROD_SSH_OPTS) \
  -o "ProxyCommand=ssh $(PROD_SSH_OPTS) -W %h:%p root@$${PROD_HOST:?PROD_HOST — IPv4 app-1}" \
  "root@$${PROD_DB_IP:?PROD_DB_IP — адрес db-1 в приватной сети}"
PROD_DB_SUBNET ?= 10.20.1.0/24

# Файлы infra/postgres — архивом в /opt/sosed/postgres, значения — строками на stdin provision.sh (не
# в argv): пароли ролей и, с 3.2, ключи репозиториев pgBackRest (PGBACKREST_REPO1_*, PGBACKREST_REPO2_*)
# и ping URL бэкапов в Healthchecks (PGBACKREST_HEALTHCHECK_URL).
# Значения задаёт CI (environment production) или владелец из менеджера паролей (Q15).
db-provision: ## PostgreSQL на db-1 (3.1b): make db-provision ENV=prod — идемпотентно; пароли ролей и PROD_* — из окружения
	@test "$(ENV)" = prod || (echo "usage: make db-provision ENV=prod"; exit 2)
	@COPYFILE_DISABLE=1 tar --no-xattrs -C infra/postgres -cf - provision.sh bootstrap.sql pgbackrest.conf.tmpl pgbackrest-backup.sh | \
	  $(PROD_DB_SSH) 'rm -rf /opt/sosed/postgres && mkdir -p /opt/sosed/postgres && tar -xf - -C /opt/sosed/postgres'
	@{ printf 'DB_LISTEN_IP=%s\nDB_SUBNET=%s\n' "$$PROD_DB_IP" "$(PROD_DB_SUBNET)"; \
	  for n in APP_DB_PASSWORD MIGRATOR_DB_PASSWORD READONLY_DB_PASSWORD BACKUP_DB_PASSWORD $$(compgen -v PGBACKREST_REPO) \
	           PGBACKREST_HEALTHCHECK_URL; do \
	    [ -z "$${!n:-}" ] || printf '%s=%s\n' "$$n" "$${!n}"; \
	  done; } | $(PROD_DB_SSH) 'bash /opt/sosed/postgres/provision.sh'
