# Stage и prod как код (DEVELOPMENT_PLAN 0.25a–0.25e). Подключается из Makefile: -include make/*.mk.
# Terraform и Kamal — только в официальных образах закреплённых версий: ставить их на Мак не нужно,
# у владельца и в CI одна и та же версия. Порядок действий — infra/runbooks/stage-bootstrap.md.
.PHONY: tf tf-check kamal

TF_IMAGE ?= hashicorp/terraform:1.16.5@sha256:c7926feace05d0f7e73542842bf3945924e955a1f782cf000ccbb8d18fa42d77
KAMAL_IMAGE ?= ghcr.io/basecamp/kamal:v2.12.0@sha256:7b5be276aa17bbe122887f6a1ff12865f4848111989699b9786083be95d98415
# -t только в терминале: в CI и в трубе его нет
TTY = $$([ -t 0 ] && echo -t)

tf: ## Terraform окружения в Docker: make tf ENV=stage ARGS='plan' (токены — infra/terraform/<env>/.env)
	@test -n "$(ENV)" && test -n "$(ARGS)" || (echo "usage: make tf ENV=stage ARGS='init|plan|apply|output stage_ipv4'"; exit 2)
	@test -f infra/terraform/$(ENV)/.env || (echo "tf: нет infra/terraform/$(ENV)/.env — make secret NAME=HCLOUD_TOKEN TARGET=tf-$(ENV)"; exit 2)
	@docker run --rm -i $(TTY) -v "$(ROOT)/infra/terraform/$(ENV):/work" -w /work \
	  --env-file infra/terraform/$(ENV)/.env $(TF_IMAGE) $(ARGS)

tf-check: ## Terraform без ключей и сети: fmt и validate всех окружений (то же, что проверяет CI)
	@for dir in infra/terraform/*/; do \
	  echo "tf-check: $$dir"; \
	  docker run --rm -v "$(ROOT)/$$dir:/work" -w /work --entrypoint sh $(TF_IMAGE) -c \
	    'terraform fmt -check -recursive && terraform init -backend=false -input=false >/dev/null && terraform validate' || exit 1; \
	done

# Переменные, которые Kamal берёт из окружения: несекретные (адрес VM, домен, владелец образов) и
# имена секретов stage из infra/kamal/secrets.stage. Значения в команду не попадают: docker run -e ИМЯ
# передаёт переменную из окружения как есть, а задаёт их владелец (менеджер паролей, Q15) или CI.
KAMAL_ENV = STAGE_HOST STAGE_DOMAIN GHCR_OWNER R2_ACCOUNT_ID STAGE_BOT_USERNAME SENTRY_DSN APP_RELEASE STAGE_LOADTEST \
  KAMAL_REGISTRY_USERNAME $(shell sed -n 's/^\([A-Z][A-Z0-9_]*\)=\$$\1$$/\1/p' infra/kamal/secrets.stage 2>/dev/null)

# ssh — через агент Docker Desktop (ssh-add ~/.ssh/id_ed25519 на Маке); образ backend Kamal не
# собирает, а скачивает на сервере (--skip-push), поэтому сокет Docker в контейнер не нужен.
kamal: ## Kamal в Docker: make kamal ARGS='deploy -d stage' (STAGE_HOST, STAGE_DOMAIN, … — из окружения)
	@test -n "$(ARGS)" || (echo "usage: make kamal ARGS='config -d stage'"; exit 2)
	@docker run --rm -i $(TTY) -v "$(ROOT):/workdir" -w /workdir \
	  -v /run/host-services/ssh-auth.sock:/run/host-services/ssh-auth.sock \
	  -e SSH_AUTH_SOCK=/run/host-services/ssh-auth.sock \
	  $(foreach v,$(KAMAL_ENV),-e $(v)) $(KAMAL_IMAGE) $(ARGS) -c infra/kamal/deploy.yml
