# Карта выбора точки в заявке (Q28, вариант A): тайлы Нови-Сада, шрифты подписей и спрайт со своих
# серверов — scripts/map/README.md. Подключается из Makefile: -include make/*.mk.
.PHONY: map-assets map-upload

# boto3 той же версии, что в backend/uv.lock: загрузка идёт мимо проекта backend (uv --no-project)
MAP_BOTO3 ?= boto3==1.43.103

map-assets: ## Карта для dev-стенда: apps/tma/public/map (собирает, если нет; Docker, git) и VITE_MAP_ASSETS_URL=/map [FORCE=1]
	@python3 scripts/map/build.py --dev $(if $(FORCE),--force)

map-upload: ## Карта в R2: make map-upload ENV=stage|prod (R2_ACCOUNT_ID, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY — из окружения)
	@test "$(ENV)" = stage || test "$(ENV)" = prod || { echo "usage: make map-upload ENV=stage|prod"; exit 2; }
	@python3 scripts/map/build.py
	@$(UV) run --no-project --quiet --with $(MAP_BOTO3) python scripts/map/upload.py --env $(ENV)
