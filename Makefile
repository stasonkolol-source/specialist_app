SHELL := /bin/bash
.DEFAULT_GOAL := help
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BACKEND := $(ROOT)/backend
UV ?= env -u VIRTUAL_ENV uv
PNPM ?= corepack pnpm
PORTS := 55442 56379 59100 59103 8000 5173
# Дополнительные цели по направлениям (например, make/frontend.mk) и их проверки для make check.
EXTRA_CHECKS :=
-include make/*.mk

COMPOSE := docker compose -p specialist-dev -f infra/compose/docker-compose.dev.yml --env-file infra/compose/.env

.PHONY: help doctor plan-check check cli lint typecheck imports test gitleaks dev-web dev-worker dev-worker-media new-module new-use-case openapi contract i18n-check-backend seeds-validate seed seed-demo demo-media dev dev-bg dev-restart dev-stop tunnel dev-bot audit image \
	pg-image up down ps logs psql pg-smoke secrets-dev garage-init secret secrets-check gen-secret gen-age test-int migrate migrate-roundtrip pg-bootstrap

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-20s %s\n", $$1, $$2}'

doctor: ## Tool versions and free local ports (step 0.1)
	@echo "uv          $$($(UV) --version 2>/dev/null || echo MISSING)"
	@echo "python      $$(cd $(BACKEND) 2>/dev/null && $(UV) run --quiet python --version 2>/dev/null || echo 'backend venv not ready')"
	@echo "node        $$(node --version 2>/dev/null || echo MISSING)"
	@echo "pnpm        $$($(PNPM) --version 2>/dev/null || echo MISSING)"
	@echo "compose     $$(docker compose version --short 2>/dev/null || echo MISSING)"
	@echo "gitleaks    $$(gitleaks version 2>/dev/null || echo 'not installed (K1)')"
	@echo "cloudflared $$(cloudflared --version 2>/dev/null | head -1 || echo 'not installed (needed from step 0.22)')"
	@for p in $(PORTS); do \
	  if lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1; then echo "port $$p    BUSY"; else echo "port $$p    free"; fi; \
	done

plan-check: ## Validate the step table of docs/DEVELOPMENT_PLAN.md
	@python3 scripts/plan_check.py

gitleaks: ## Secrets in git history and in uncommitted changes of tracked files (.env are ignored)
	@if command -v gitleaks >/dev/null 2>&1; then \
	  gitleaks git --no-banner --redact --log-level warn . && \
	  gitleaks git --pre-commit --no-banner --redact --log-level warn . && echo "gitleaks: no leaks"; \
	  else echo "SKIP gitleaks (not installed yet — K1)"; fi

cli: ## Backend CLI: make cli ARGS='--help'
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli $(ARGS)

lint: ## ruff check + format check
	@cd $(BACKEND) && $(UV) run ruff check && $(UV) run ruff format --check

typecheck: ## mypy strict on src/app
	@cd $(BACKEND) && $(UV) run mypy

imports: ## import-linter contracts (module layers, pure core, DAG)
	@cd $(BACKEND) && $(UV) run lint-imports

test: ## Unit tests
	@cd $(BACKEND) && $(UV) run pytest -m unit -q

test-int: pg-image ## Integration tests on testcontainers (our PostGIS image, Valkey, Garage)
	@cd $(BACKEND) && $(UV) run pytest -m integration -q

bench-search: pg-image ## Выдача специалистов на 50 000 строк read-model: p95 набора запросов < 200 мс (4.2)
	@cd $(BACKEND) && $(UV) run pytest -m bench -k search_query -q

# --- Локальное окружение (шаг 0.3). Только compose-проект specialist-dev. ---

secrets-dev: ## Сгенерировать dev-пароли и секреты в .env (значения не печатаются)
	@python3 scripts/secrets_dev.py

pg-image: ## Собрать образ PostgreSQL 18 + PostGIS
	@$(COMPOSE) build postgres

up: secrets-dev ## Поднять postgres, valkey, garage
	@$(COMPOSE) up -d --wait

down: ## Остановить сервисы (тома сохраняются)
	@$(COMPOSE) down

ps: ## Статус сервисов
	@$(COMPOSE) ps

logs: ## Логи сервисов
	@$(COMPOSE) logs --tail=100 -f

psql: ## psql под ролью app
	@set -a; . infra/compose/.env; set +a; \
	$(COMPOSE) exec -e PGPASSWORD="$$APP_DB_PASSWORD" postgres psql -h 127.0.0.1 -U app -d specialist

pg-smoke: ## Smoke БД: локаль, pg_trgm, PostGIS, роли (ENV=stage — accessory на VM stage; ENV=prod — db-1 через app-1)
	@if [ "$(ENV)" = stage ]; then \
	  ssh -o BatchMode=yes "root@$${STAGE_HOST:?STAGE_HOST — IPv4 VM stage}" \
	    'PG_SMOKE_CONTAINER=sosed-postgres bash -s' < scripts/pg_smoke.sh; \
	elif [ "$(ENV)" = prod ]; then \
	  $(PROD_DB_SSH) 'PG_SMOKE_LOCAL=1 bash -s' < scripts/pg_smoke.sh; \
	else scripts/pg_smoke.sh; fi

secret: ## Скрытый ввод секрета: make secret NAME=TELEGRAM_BOT_TOKEN TARGET=dev
	@test -n "$(NAME)" && test -n "$(TARGET)" || (echo "usage: make secret NAME=… TARGET=dev|tf-stage|tf-prod|tf-zone|tf-monitoring|monitoring|stage|production"; exit 2)
	@python3 scripts/secret.py "$(NAME)" "$(TARGET)"

secrets-check: ## Какие переменные заданы или пусты — без значений
	@python3 scripts/secrets_check.py

gen-secret: ## Случайный секрет stage/prod: make gen-secret NAME=APP_DB_PASSWORD ENV=stage (без NAME — только печать)
	@python3 scripts/gen_secret.py $(NAME) $(ENV)

gen-age: ## age-ключ SOPS — только при Q1(а); по умолчанию Q1(б), секреты в GitHub environments
	@echo "gen-age: Q1 = (б) — секреты stage и prod в GitHub environments, SOPS и age-ключ не нужны (OWNER_CHECKLIST, K18)"; exit 2

pg-bootstrap: ## Повторно применить infra/postgres/bootstrap.sql к dev-БД (идемпотентно)
	@set -a; . infra/compose/.env; set +a; \
	$(COMPOSE) exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
	  -v dbname=specialist -v app_password="$$APP_DB_PASSWORD" -v migrator_password="$$MIGRATOR_DB_PASSWORD" \
	  -v readonly_password="$$READONLY_DB_PASSWORD" -v backup_password="$$BACKUP_DB_PASSWORD" \
	  -v monitoring_password="$${MONITORING_DB_PASSWORD:-}" \
	  -q -f /opt/specialist/bootstrap.sql && echo "pg-bootstrap: OK"

migrate: ## alembic upgrade head на dev-БД (роль migrator)
	@cd $(BACKEND) && $(UV) run alembic upgrade head

migrate-roundtrip: pg-image ## Раунд-трип миграций в testcontainers: upgrade → downgrade base → upgrade → check → heads
	@cd $(BACKEND) && $(UV) run pytest -m integration -q -k "roundtrip"

i18n-check: i18n-check-backend

i18n-check-backend: ## Backend: sr_Latn сгенерирован из актуального sr_Cyrl, ключи ru = sr_Cyrl
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli i18n check

audit: ## Уязвимости зависимостей (pip-audit, pnpm audit) и секреты (gitleaks)
	@cd $(BACKEND) && $(UV) export --locked --no-hashes --format requirements-txt --no-emit-project \
	  | $(UV) tool run pip-audit==2.10.1 -r /dev/stdin --no-deps --disable-pip --progress-spinner off
	@$(PNPM) audit --audit-level low
	@$(MAKE) --no-print-directory gitleaks

image: ## Собрать образ backend: specialist/backend:dev (роль — аргумент: web | bot | worker | cli …)
	@docker build -t specialist/backend:dev $(BACKEND)

seed: ## Загрузить сиды в dev-БД идемпотентно: гео (1.3a), каталог (1.3b), словарь модерации (2.4)
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli seed

seed-demo: ## Демо-люди для dev и stage (2.8c): SCALE=small | lab, DEMO_LANG=ru | sr | mixed, REPLACE=1 — заменить прежних (dev)
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli seed-demo --scale $(or $(SCALE),small) \
		--lang $(or $(DEMO_LANG),ru) $(if $(REPLACE),--replace)

demo-media: ## Настоящие фото и аватары для seed-demo в backend/.cache/demo-media (не в git; scripts/demo-media)
	@python3 scripts/demo-media/fetch.py

seeds-validate: ## Сиды: гео, таксономия, запросы (0.27), словарь модерации и его примеры (2.4)
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli seeds-validate

openapi: ## Контракты: backend/openapi.json и admin-openapi.json из кода, перегенерация api-client
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.cli openapi
	@if grep -q '"generate"' packages/api-client/package.json 2>/dev/null; then $(PNPM) -F api-client generate; fi

contract: ## Контрактные тесты schemathesis против живого API (testcontainers)
	@cd $(BACKEND) && $(UV) run pytest tests/contract -q

new-module: ## Новый модуль по шаблону copier: make new-module NAME=<имя>
	@test -n "$(NAME)" || (echo "usage: make new-module NAME=<имя>"; exit 2)
	@cd $(BACKEND) && $(UV) run python ../scripts/new_module.py module "$(NAME)"

new-use-case: ## Новый use case: make new-use-case MODULE=<модуль> NAME=<глагол_объект>
	@test -n "$(MODULE)" && test -n "$(NAME)" || (echo "usage: make new-use-case MODULE=… NAME=…"; exit 2)
	@cd $(BACKEND) && $(UV) run python ../scripts/new_module.py use-case "$(MODULE)" "$(NAME)"

dev: ## Весь dev-стенд: compose, миграции, сиды, туннели, web, bot, worker, tma (TUNNEL=0 — без туннелей)
	@cd scripts && TUNNEL=$(or $(TUNNEL),1) $(UV) run --no-project --quiet python dev.py

dev-bg: ## Тот же стенд в фоне: переживает закрытие терминала и IDE; лог .tunnel-logs/dev.log
	@cd scripts && TUNNEL=$(or $(TUNNEL),1) $(UV) run --no-project --quiet python dev.py --background

dev-restart: ## Перезапустить процессы стенда (новый код бота и воркеров); туннели и адреса остаются
	@cd scripts && $(UV) run --no-project --quiet python dev.py --restart

dev-stop: ## Остановить стенд, запущенный make dev или make dev-bg
	@cd scripts && $(UV) run --no-project --quiet python dev.py --stop

tunnel: ## Quick tunnel cloudflared на Mini App и Garage: адреса в .env, menu button бота
	@cd scripts && $(UV) run --no-project --quiet python tunnel.py

dev-bot: ## Бот в режиме polling (dev)
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.bot

dev-web: ## API на 127.0.0.1:8000 с автоперезагрузкой (/up, /api/v1/docs)
	@cd $(BACKEND) && $(UV) run uvicorn app.entrypoints.web:create --factory --reload \
	  --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers --no-server-header

dev-worker: ## Воркер задач на dev-стенде (очереди default и notifications; ROLE=worker-media — media)
	@cd $(BACKEND) && $(UV) run python -m app.entrypoints.worker --role $(or $(ROLE),worker)

dev-worker-media: ## Воркер обработки медиа (очередь media): make dev-worker ROLE=worker-media
	@$(MAKE) --no-print-directory dev-worker ROLE=worker-media

garage-init: ## Ключ, бакеты и CORS в Garage; ключи — в backend/.env
	@cd scripts && $(UV) run --no-project --quiet --with boto3 python garage_init.py

check: plan-check gitleaks lint typecheck imports i18n-check-backend seeds-validate test test-int $(EXTRA_CHECKS) ## Definition of Done checks available so far
	@echo "check: OK"
