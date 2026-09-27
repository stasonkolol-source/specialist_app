# Фронтенд (pnpm + Turborepo, ADR-0012). Подключается из Makefile: -include make/*.mk.
.PHONY: fe-install fe-generate check-frontend

EXTRA_CHECKS += check-frontend

fe-install: ## Frontend: install pnpm workspace deps (frozen lockfile)
	@$(PNPM) install --frozen-lockfile --prefer-offline

fe-generate: ## Frontend: regenerate design tokens and fonts CSS from tokens.json
	@$(PNPM) -F design-tokens generate

check-frontend: fe-install ## Frontend: prettier, typecheck, lint, tests, token contrast
	@$(PNPM) format:check
	@$(PNPM) turbo run typecheck lint test
	@$(PNPM) --silent -F design-tokens check:contrast >/dev/null && echo "contrast: ok"
