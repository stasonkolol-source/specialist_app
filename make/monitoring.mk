# Наблюдаемость как код (DEVELOPMENT_PLAN 3.3): конфиг Alloy, алерты и дашборды из infra/monitoring.
# Инструменты — в закреплённых образах, как Terraform и Kamal (make/infra.mk). Без APPLY=1 цели только
# проверяют и показывают, что изменится; ключи Grafana Cloud (K35) — в infra/monitoring/.env у владельца
# (make secret NAME=… TARGET=monitoring), в git их нет. Порядок — infra/runbooks/prod-bootstrap.md,
# «Наблюдаемость».
.PHONY: monitoring-check monitoring-rules monitoring-dashboards

ALLOY_IMAGE ?= grafana/alloy:v1.20.1@sha256:2aa2099af76c0098d4af7a4d6e48f86cb66dc1a000222ad927a1c67c6542d13f
PROM_IMAGE ?= prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e
MIMIRTOOL_IMAGE ?= grafana/mimirtool:3.2.1@sha256:0aa95bd23b51c3318dbe7e9a1f0029721d6c09e0a9fa1cd3c5192313cf1b35fa
MONITORING_ENV = infra/monitoring/.env
# пространство имён правил в ruler Grafana Cloud: sync трогает только его
RULES_NAMESPACE = sosed

monitoring-check: ## Без ключей: alloy validate (stage и prod), promtool check/test rules, JSON дашбордов
	@for files in config.alloy "config.alloy db-1.alloy"; do \
	  mounts=""; for f in $$files; do mounts="$$mounts -v $(ROOT)/infra/monitoring/alloy/$$f:/etc/alloy/$$f:ro"; done; \
	  docker run --rm --network none $$mounts $(ALLOY_IMAGE) validate /etc/alloy >/dev/null || exit 1; \
	  for f in $$files; do \
	    docker run --rm --network none -v "$(ROOT)/infra/monitoring/alloy:/a:ro" $(ALLOY_IMAGE) fmt /a/$$f | \
	      cmp -s - infra/monitoring/alloy/$$f || { echo "monitoring-check: $$f не по alloy fmt"; exit 1; }; \
	  done; \
	  echo "monitoring-check: alloy validate OK ($$files)"; \
	done
	@docker run --rm --network none -v "$(ROOT)/infra/monitoring/rules:/rules:ro" -w /rules --entrypoint promtool \
	  $(PROM_IMAGE) check rules sosed.yaml
	@docker run --rm --network none -v "$(ROOT)/infra/monitoring/rules:/rules:ro" -w /rules --entrypoint promtool \
	  $(PROM_IMAGE) test rules tests/sosed.test.yaml
	@python3 -c 'import json, pathlib, sys; [json.loads(p.read_text()) for p in sorted(pathlib.Path(sys.argv[1]).glob("*.json"))]' \
	  infra/monitoring/dashboards && echo "monitoring-check: дашборды — валидный JSON"

# Правила в формате Prometheus (их понимает promtool); mimirtool хочет ещё ключ namespace — его
# добавляет временная копия. Без APPLY=1 — rules diff: что изменилось бы в Grafana Cloud.
monitoring-rules: ## Алерты в Grafana Cloud (K35): make monitoring-rules [APPLY=1] — без APPLY только diff
	@docker run --rm --network none -v "$(ROOT)/infra/monitoring/rules:/rules:ro" -w /rules --entrypoint promtool \
	  $(PROM_IMAGE) check rules sosed.yaml
	@test -f $(MONITORING_ENV) || (echo "monitoring-rules: нет $(MONITORING_ENV) — MIMIR_ADDRESS, MIMIR_TENANT_ID, MIMIR_API_KEY (K35)"; exit 2)
	@tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	  { echo "namespace: $(RULES_NAMESPACE)"; cat infra/monitoring/rules/sosed.yaml; } > "$$tmp/sosed.yaml"; \
	  docker run --rm -v "$$tmp:/rules:ro" --env-file $(MONITORING_ENV) $(MIMIRTOOL_IMAGE) \
	    rules $(if $(APPLY),sync,diff) --namespaces=$(RULES_NAMESPACE) /rules/sosed.yaml

# Дашборды — через HTTP API Grafana токеном service account (K35, роль Editor), в папку «Соседи».
# Без APPLY=1 — только список того, что ушло бы, без запросов к Grafana.
monitoring-dashboards: ## Дашборды в Grafana Cloud (K35): make monitoring-dashboards [APPLY=1] — без APPLY только список
	@test -f $(MONITORING_ENV) || (echo "monitoring-dashboards: нет $(MONITORING_ENV) — GRAFANA_URL, GRAFANA_SA_TOKEN (K35)"; exit 2)
	@python3 scripts/grafana_dashboards.py --env-file $(MONITORING_ENV) $(if $(APPLY),--apply) infra/monitoring/dashboards/*.json
