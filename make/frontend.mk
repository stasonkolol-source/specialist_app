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
