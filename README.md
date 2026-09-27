# «Соседи»

Мастера, подработка и (после MVP) вещи для русскоязычных в Сербии — Telegram-бот и Mini App.

## Документы

| Документ | Что в нём |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура: модули, данные, API, инфраструктура, roadmap |
| [docs/PRODUCT.md](docs/PRODUCT.md) | Продукт, роли, экраны S01–S58, user flows, метрики |
| [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | Пошаговый план разработки M0–M8 (114 шагов) |
| [docs/OWNER_CHECKLIST.md](docs/OWNER_CHECKLIST.md) | Что нужно от владельца: аккаунты, ключи, решения |
| [docs/adr/](docs/adr/README.md) | Архитектурные решения (ADR-0001…0020) |
| [design/](design/README.md) | Утверждённый дизайн: токены `ui.css`, спецификация, 72 макета |

## Требования

- macOS или Linux, Docker с Compose v2
- [uv](https://docs.astral.sh/uv/) ≥ 0.12, Python ≥ 3.14.5 (ставит uv: `backend/.python-version`)
- Node 24 и pnpm через corepack (`corepack enable pnpm`)
- gitleaks и pre-commit (`uvx pre-commit install`)

## Команды

Все команды — из корня репозитория, список — `make help`.

| Команда | Что делает |
|---|---|
| `make doctor` | Версии инструментов и свободные ли локальные порты |
| `make plan-check` | Проверка таблицы шагов плана |
| `make check` | Все проверки Definition of Done, доступные на текущем шаге |
| `make lint`, `make typecheck`, `make imports`, `make test` | ruff, mypy strict, контракты import-linter, unit-тесты |
| `make cli ARGS='--help'` | Служебные команды backend |

## Секреты

В git секреты не попадают: `.env`-файлы игнорируются, в репозитории только `*.env.example`, коммиты проверяет gitleaks. Правила — [docs/OWNER_CHECKLIST.md](docs/OWNER_CHECKLIST.md#правила-обращения-с-секретами).
