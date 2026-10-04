# Нагрузочный прогон (DEVELOPMENT_PLAN 8.3): k6 в официальном образе закреплённой версии, сценарии —
# infra/loadtest, порядок прогона на stage и шаблон отчёта — docs/loadtest/README.md.
# Подключается из Makefile: -include make/*.mk.
.PHONY: loadtest loadtest-users

K6_IMAGE ?= grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34
LOADTEST_USERS := infra/loadtest/.users.json
# сколько initData печатать: пул setup() (POOL, 60) и пользователи сценария login
LOADTEST_COUNT ?= 100
# локально — Мак владельца со стендом: только smoke (2 VU, 30 с, гостевые чтения)
LOADTEST_URL_local = http://host.docker.internal:8000
LOADTEST_URL_stage = https://stage-api.$(STAGE_DOMAIN)
LOADTEST_PROFILE_local = smoke
LOADTEST_PROFILE_stage = load

loadtest: ## k6 в Docker: make loadtest ENV=local|stage [SCENARIO=feed,chat] [PROFILE=smoke|load] [HOLD=5m]
	@case "$(ENV)" in local|stage) ;; *) echo "usage: make loadtest ENV=local|stage [SCENARIO=…] [PROFILE=smoke|load]"; exit 2;; esac
	@test "$(ENV)" != stage -o -n "$(STAGE_DOMAIN)" || (echo "loadtest: STAGE_DOMAIN не задан (домен stage, Q9)"; exit 2)
	@test "$(ENV)" != local -o "$(or $(PROFILE),smoke)" = smoke || (echo "loadtest: локально только PROFILE=smoke — полный прогон только на stage"; exit 2)
	@test "$(or $(PROFILE),$(LOADTEST_PROFILE_$(ENV)))" = smoke -o -s $(LOADTEST_USERS) || (echo "loadtest: нет $(LOADTEST_USERS) — make loadtest-users ENV=$(ENV)"; exit 2)
	@docker run --rm -i $(TTY) --add-host host.docker.internal:host-gateway \
	  -v "$(ROOT)/infra/loadtest:/loadtest" -w /loadtest \
	  -e BASE_URL=$(or $(BASE_URL),$(LOADTEST_URL_$(ENV))) -e PROFILE=$(or $(PROFILE),$(LOADTEST_PROFILE_$(ENV))) \
	  -e USERS_FILE=$(if $(wildcard $(LOADTEST_USERS)),/loadtest/.users.json) \
	  -e SCENARIO -e PEAK_RPS -e POOL -e HOLD -e CITY -e NET_MS -e RESPOND_RPS -e LOGINS_PER_MINUTE \
	  $(K6_IMAGE) run --quiet main.js

# initData годен час: печатать прямо перед прогоном. На stage — в контейнере web (токен бота
# окружения есть только там), на dev — через make cli. В файле — не секрет, но и не для git.
loadtest-users: ## initData демо-специалистов для k6: make loadtest-users ENV=local|stage [LOADTEST_COUNT=100]
	@case "$(ENV)" in \
	  stage) test -n "$(STAGE_HOST)" || { echo "loadtest-users: STAGE_HOST не задан"; exit 2; }; \
	    ssh root@$(STAGE_HOST) 'docker exec $$(docker ps -qf label=role=web | head -1) sosed cli loadtest-initdata --count $(LOADTEST_COUNT)' > $(LOADTEST_USERS) ;; \
	  local) cd $(BACKEND) && $(UV) run --quiet python -m app.entrypoints.cli loadtest-initdata --count $(LOADTEST_COUNT) > $(ROOT)/$(LOADTEST_USERS) ;; \
	  *) echo "usage: make loadtest-users ENV=local|stage"; exit 2 ;; \
	esac
	@echo "$(LOADTEST_USERS): $(LOADTEST_COUNT) initData, годны час"
