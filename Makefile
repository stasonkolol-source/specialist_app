SHELL := /bin/bash
.DEFAULT_GOAL := help
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BACKEND := $(ROOT)/backend
UV ?= env -u VIRTUAL_ENV uv
PNPM ?= corepack pnpm
PORTS := 55442 56379 59100 59103 8000 5173
COMPOSE := docker compose -p specialist-dev -f infra/compose/docker-compose.dev.yml --env-file infra/compose/.env

.PHONY: help doctor plan-check check cli lint typecheck imports test gitleaks \
	pg-image up down ps logs psql pg-smoke secrets-dev garage-init

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-20s %s\n", $$1, $$2}'

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

gitleaks: ## Scan the working tree for secrets
	@if command -v gitleaks >/dev/null 2>&1; then gitleaks dir --no-banner --redact . ; \
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

pg-smoke: ## Smoke БД: локаль, pg_trgm, PostGIS, роли
	@scripts/pg_smoke.sh

garage-init: ## Ключ, бакеты и CORS в Garage; ключи — в backend/.env
	@cd scripts && $(UV) run --no-project --quiet --with boto3 python garage_init.py

check: plan-check gitleaks lint typecheck imports test ## Definition of Done checks available so far
	@echo "SKIP integration tests (step 0.5a)"
	@echo "SKIP migrate-roundtrip (step 0.9)"
	@echo "SKIP frontend checks (step 0.16a)"
	@echo "check: OK"
