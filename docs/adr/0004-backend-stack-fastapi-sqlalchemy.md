# ADR-0004: Backend-стек — Python 3.14, FastAPI, SQLAlchemy 2.1 + psycopg 3

- **Статус:** принято
- **Дата:** 2026-09-26
- **Связанные документы:** [research/03-backend-stack.md](../research/03-backend-stack.md), [ADR-0002](0002-modular-monolith.md), [ADR-0008](0008-background-jobs-and-outbox.md), [ADR-0011](0011-telegram-bot-integration.md)

## Контекст

- **Вводные:** backend на Python, PostgreSQL обязателен, команда 1–2 разработчика.
- **Процессы с общей бизнес-логикой:** REST API для Mini App и мобильного приложения, Telegram-бот на aiogram (async), фоновые воркеры (рассылки, медиа, периодические задачи). Все три вызывают одни и те же application services.
- **Бэк-офис** для модерации нужен, но на старте небольшой: несколько модераторов, простые очереди.
- **Время жизни.** Стек должен прожить минимум 2–3 года без вынужденной миграции.

## Рассмотренные варианты

| Вариант | За | Против |
|---|---|---|
| **FastAPI + SQLAlchemy 2.x async** | Async-first по всей цепочке (API, aiogram, воркеры — одна модель исполнения); крупнейшая экосистема; OpenAPI из type hints; FastAPI Team — 7 человек, плюс компания FastAPI Labs | Версия 0.x: ломающие изменения приходят в minor-релизах (5 таких за 2025-12…2026-06: 0.125, 0.128, 0.129, 0.132, 0.137); админки «из коробки» нет |
| Litestar 2.x | Встроенный DI, DTO, msgspec | v3 с ломающим DI уже анонсирован; мейнтейнеры сами пишут о нехватке ресурсов; сообщество меньше |
| Django 6.1 + DRF / Ninja | Лучшая админка, LTS-релизы, «батарейки» | В async-режиме ORM не поддерживает транзакции, DRF синхронный. Асинхронный бот и рассылки жили бы на `sync_to_async` — два стиля кода |
| FastAPI + Django admin на той же БД | Лучшая админка | Две ORM и две системы миграций, каждая модель описана дважды |

## Решение

| Слой | Выбор (версии на 2026-09-26) |
|---|---|
| Runtime | CPython **3.14.x, не ниже 3.14.5** (откат incremental GC). `requires-python = ">=3.14,<3.15"`. Free-threaded сборку не используем |
| HTTP | **FastAPI `~=0.141.1`** (Starlette 1.7), **Uvicorn[standard] 0.54** за reverse proxy; Granian — кандидат после нагрузочного теста |
| Валидация, настройки | **Pydantic 2.13.x** (потолок из-за aiogram `<2.14`), pydantic-settings 2.15. Pydantic — только на границах (API, настройки, payload задач); доменные сущности — обычные классы и dataclass |
| ORM и миграции | **SQLAlchemy 2.1.x** `[asyncio]`, **psycopg[binary,pool] 3.3**, **Alembic 1.20**, GeoAlchemy2 0.20 + Shapely 2.1 |
| DI | **dishka 1.10**: один контейнер на API, бота и воркер |
| Кэш, лимиты | Valkey 9.1 + redis-py 7.4 (не 8.x из-за пинов aiogram и `limits`), `limits` 5.8 для rate limiting |
| Auth | PyJWT 2.15 (наши JWT), joserfc 1.7 (JWKS и ID-токены Telegram/Apple), authlib 1.8 (OAuth-клиенты), pwdlib[argon2] (пароли персонала) |
| Админка | **SQLAdmin 0.32** внутри FastAPI на `/admin` + быстрая модерация в закрытом Telegram-чате модераторов ([ADR-0016](0016-trust-safety-and-reviews.md)) |
| i18n | Babel 2.18 + gettext, каталоги общие для API и бота ([ADR-0013](0013-i18n-multilingual-content.md)) |
| Observability | sentry-sdk 2.70, structlog 26.1, prometheus-client 0.26; OpenTelemetry 1.45 — вторым шагом |
| Тесты | pytest 9.1, pytest-asyncio 1.4, testcontainers 4.15 (PostGIS, Valkey), httpx 0.28, polyfactory 3.3, schemathesis 4.28 (property-based по OpenAPI) |
| Качество | uv 0.12, ruff 0.16, mypy 2.3 (strict для domain и application), import-linter 2.15 (границы модулей), pre-commit |

**Почему psycopg 3, а не asyncpg.**
- Это драйвер по умолчанию в SQLAlchemy 2.1.
- Только с ним Procrastinate ставит задачу в той же транзакции, что и бизнес-запись ([ADR-0008](0008-background-jobs-and-outbox.md)).
- У asyncpg за последний год был один релиз.
- Если на горячих read-путях замеры покажут заметную разницу, asyncpg можно подключить точечно.

## Последствия

**Положительные**

- Один язык исполнения (asyncio) для API, бота и воркеров: application services — обычные `async def`, их вызывают все три интерфейса.
- OpenAPI генерируется автоматически и служит контрактом для клиентов ([ADR-0003](0003-api-first-rest-openapi.md)).
- Всё берётся из PyPI, не нужны платные сервисы и отдельная инфраструктура.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| FastAPI 0.x | Пин minor-версии; обновление осознанно раз в 1–2 месяца; HTTP-слой тонкий и покрыт schemathesis |
| SQLAlchemy 2.1.0 вышла 2026-09-24, часть экосистемы ещё требует `<2.1` (SQLModel, fastapi-users), GeoAlchemy2 совместимость не заявляет | Smoke-тест в первую неделю; запасной вариант — 2.0.54. SQLModel и fastapi-users не используем |
| Админка беднее Django admin | На MVP хватает SQLAdmin и Telegram-чата модераторов. При росте штата — отдельный back-office SPA поверх того же admin API |
| Пины aiogram (`pydantic<2.14`, `aiohttp<3.15`, `redis<8`) тормозят апгрейды | Renovate/Dependabot; aiogram выходит ежемесячно |

**Что сделать (спайк, первая неделя)**

1. Скелет проекта: `uv`, структура модулей, import-linter-контракты, dishka, Alembic со схемами по модулям.
2. Smoke-тест SQLAlchemy 2.1 + GeoAlchemy2 + psycopg на PostGIS.
3. Интеграционный тест транзакционной постановки задач Procrastinate через соединение SQLAlchemy ([ADR-0008](0008-background-jobs-and-outbox.md)).
4. Нагрузочный smoke (Uvicorn против Granian) на типовых запросах каталога.
