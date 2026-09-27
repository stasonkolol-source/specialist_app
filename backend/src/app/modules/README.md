# Как устроен модуль

Каждый доменный модуль — пакет `modules/<имя>/` с одинаковыми слоями (ADR-0020 §1).
Эталон — `identity`: с него сняты шаблоны `backend/templates/`.

```text
modules/<имя>/
├── api.py            # контракт для других модулей: Protocol <Имя>Api, DTO, публичные ошибки
├── errors.py         # ошибки модуля с code (snake_case, уникален на проект)
├── di.py             # провайдер dishka: порты → реализации, <Имя>Config, use cases
├── domain/           # чистый Python: агрегаты, value objects, state machine, политики
├── application/      # use_cases/, ports.py, dto.py, config.py, facade.py
├── infrastructure/   # models.py (<Сущность>Row), mappers.py, repositories.py, queries.py
├── http/             # по необходимости: router.py (тонкие хендлеры), schemas.py (In/Out)
├── bot/, admin/, tasks.py   # по необходимости
└── tests/{unit,integration,api}/
```

## Создать

```bash
make new-module NAME=<имя>                          # слои, провайдер, схема, контракт import-linter
make new-use-case MODULE=<модуль> NAME=<глагол_объект>   # use case, команда, тест, строка в di.py
```

После `new-module` поставьте модуль в слой DAG (`module-dag` в `backend/.importlinter`,
ARCHITECTURE §5.4). Первая миграция модуля — `<имя>_0001_<slug>.py`, она же создаёт схему.
MetaData моделей добавьте в `app/entrypoints/_metadata.py`, роутер `http/router.py`
подключится сам (`_wiring.module_routers`), задачи из `tasks.py` — тоже.

FK на таблицу другого модуля (только вниз по DAG, ARCHITECTURE §5.2 п. 4) пишется в
миграции руками (`op.create_foreign_key(..., referent_schema="geo")`), в модели — колонка
без `ForeignKey`: MetaData модуля чужих таблиц не знает, и ORM не разрешил бы ссылку при
flush. `alembic check` такие FK не сравнивает (`migrations/env.py`). Пример —
`identity.users.home_city_id` в `identity_0002`.

## Правила, которые проверяются автоматически

| Правило | Где |
|---|---|
| Слои модуля, DAG, «снаружи виден только `api`», чистое ядро | `backend/.importlinter` |
| Импорты ядра: в `domain`, `api`, `errors` — только stdlib, в `application` — ещё `structlog` | `tests/architecture/test_code_rules.py` |
| `commit`/`rollback` только в `platform/db`; нет `gather`/`TaskGroup` и `**asdict(` | `tests/architecture/test_code_rules.py` |
| Обязательные слои, имена use cases (`<Класс>` и `<Класс>Command`), ORM (`…Row`), задач (`<модуль>.…`) | `tests/architecture/test_code_rules.py` |
| Миграции `<модуль>_NNNN_<slug>` | `tests/architecture/test_migrations_naming.py` |
| Каждая `DomainError` в таблице ADR-0020 §9, уникальный `code`, `operationId` | `tests/architecture/test_errors_and_routes.py` |
| Контейнер собирается для web, bot и worker | `tests/integration/test_di.py` |

Остальное — чек-лист в шаблоне PR (`.github/pull_request_template.md`).
