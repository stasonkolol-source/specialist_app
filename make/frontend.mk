# Фронтенд (pnpm + Turborepo, ADR-0012). Подключается из Makefile: -include make/*.mk.
.PHONY: fe-install fe-generate check-frontend i18n-check i18n-check-frontend

EXTRA_CHECKS += check-frontend

fe-install: ## Frontend: install pnpm workspace deps (frozen lockfile)
	@$(PNPM) install --frozen-lockfile --prefer-offline

fe-generate: ## Frontend: regenerate design tokens, fonts CSS and sr-Latn catalogs
	@$(PNPM) -F design-tokens generate
	@$(PNPM) -F i18n generate

check-frontend: fe-install ## Frontend: prettier, typecheck, lint, tests, token contrast, i18n catalogs
	@$(PNPM) format:check
	@$(PNPM) turbo run typecheck lint test
	@$(PNPM) --silent -F design-tokens check:contrast >/dev/null && echo "contrast: ok"
	@$(PNPM) --silent -F i18n i18n:check

# Без рецепта: каталоги backend (шаг 1.2) добавят сюда свою цель-зависимость
i18n-check: i18n-check-frontend ## Translation catalogs: sr-Latn up to date, keys and ICU consistent

i18n-check-frontend: fe-install
	@$(PNPM) --silent -F i18n i18n:check

# Playwright — только в Docker-образе той же версии, что @playwright/test. Репозиторий смонтирован по тому же
# пути, что на хосте: симлинки pnpm и пути в отчётах совпадают. Сборка (e2e:build) — на хосте.
PLAYWRIGHT_IMAGE ?= mcr.microsoft.com/playwright:v1.63.0-noble
PKG ?= ui-web
E2E_DIR = $(firstword $(wildcard $(ROOT)/packages/$(PKG) $(ROOT)/apps/$(PKG)))

.PHONY: e2e design-render design-compare
design-render: fe-install ## Design references: PNG of every artboard into design/reference [GREP=S03]
	@mkdir -p "$(ROOT)/design/reference"
	@docker run --rm --init --ipc=host -v "$(ROOT):$(ROOT)" -w "$(ROOT)/packages/ui-web" $(PLAYWRIGHT_IMAGE) \
	  node node_modules/@playwright/test/cli.js test -c playwright.design.config.ts $(if $(GREP),--grep "$(GREP)")

design-compare: ## Report «reference next to actual»: make design-compare [GREP=S03]
	@node packages/ui-web/scripts/design-compare.mjs $(GREP)

e2e: fe-install ## Playwright in Docker: make e2e [PKG=ui-web] [GREP=…] [UPDATE=1]
	@$(PNPM) -F $(PKG) e2e:build
	@docker run --rm --init --ipc=host -e CI -v "$(ROOT):$(ROOT)" -w "$(E2E_DIR)" $(PLAYWRIGHT_IMAGE) \
	  node node_modules/@playwright/test/cli.js test $(if $(GREP),--grep "$(GREP)") $(if $(UPDATE),--update-snapshots)
