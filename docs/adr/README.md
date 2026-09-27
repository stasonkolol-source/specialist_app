# Architecture Decision Records

Каждое значимое архитектурное решение описано отдельным документом. В нём есть контекст, рассмотренные варианты, само решение и его последствия. Порядок работы с ADR — [ADR-0001](0001-record-architecture-decisions.md).

| # | Решение | Статус |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Фиксируем архитектурные решения в ADR | принято |
| [0002](0002-modular-monolith.md) | Модульный монолит: 16 модулей (15 доменных + shared kernel), схема PostgreSQL на модуль, фасады, DAG зависимостей, события | принято, дополнено ADR-0019 |
| [0003](0003-api-first-rest-openapi.md) | API-first: REST + OpenAPI 3.1, `/api/v1`, RFC 9457, keyset, идемпотентность; бот — адаптер in-process | принято |
| [0004](0004-backend-stack-fastapi-sqlalchemy.md) | Python 3.14, FastAPI, SQLAlchemy 2.1 + psycopg 3, Pydantic 2.13, dishka, SQLAdmin | принято |
| [0005](0005-postgresql-postgis-data-platform.md) | PostgreSQL 18 + PostGIS 3.6: UTF-8 `LC_CTYPE`, параметры роли приложения, UUIDv7, миграции expand/contract | принято |
| [0006](0006-search-in-postgresql.md) | Поиск в PostgreSQL: read-model, многоязычная таксономия, `sr_unaccent`, pg_trgm, PostGIS; триггеры выноса в Typesense / Meilisearch | принято, дополнено ADR-0019 |
| [0007](0007-media-storage-and-processing.md) | Медиа: Cloudflare R2 (EU), presigned PUT, обработка в воркере (Pillow, ffmpeg), CDN; локально Garage | принято, дополнено ADR-0019 |
| [0008](0008-background-jobs-and-outbox.md) | Фоновые задачи на Procrastinate: очередь в PostgreSQL, постановка в транзакции вместо отдельного outbox | принято, нужен спайк |
| [0009](0009-authentication-and-identity.md) | Аутентификация: initData → JWT + refresh, `users` + `auth_identities`; этап 2 — Telegram OIDC, Sign in with Apple, телефон | принято, сроки уточнены ADR-0018 |
| [0010](0010-messaging-hybrid-chat.md) | Общение — гибрид: свой backend переписки + доставка через бота; контакты — только после договорённости; без топиков бота | принято, дополнено ADR-0019 |
| [0011](0011-telegram-bot-integration.md) | Telegram: один бот с Main Mini App, aiogram 3.31, webhook, отдельный процесс; схема deep links; рассылки с лимитами | принято, дополнено ADR-0019 |
| [0012](0012-mini-app-frontend-and-mobile-path.md) | Фронтенд: React + Vite, одна сборка для Telegram и веба, общий TS-core в монорепо, Expo на этапе 2 | принято |
| [0013](0013-i18n-multilingual-content.md) | Мультиязычность: MVP — ru, sr-Latn, sr-Cyrl, en — v1; исходник сербского — кириллица; справочники в JSONB, UGC в оригинале | принято |
| [0014](0014-monetization-and-billing.md) | Монетизация: бесплатный MVP → Pro и бусты за Stars после ворот ликвидности; entitlements для всех каналов (`billing` — v1) | принято, сроки уточнены ADR-0018, дополнено ADR-0019 |
| [0015](0015-hosting-and-deployment.md) | Hetzner Cloud (DE), Cloudflare, Kamal 2, GitHub Actions, pgBackRest, наблюдаемость на бесплатных тарифах | принято |
| [0016](0016-trust-safety-and-reviews.md) | Trust & safety: уровни доверия, лестница верификации, модерация по риску (LLM-классификатор в MVP), очереди с SLA, отзывы только по сделкам (double-blind — v1) | принято, сроки уточнены ADR-0018, дополнено ADR-0019 |
| [0017](0017-payments-for-services-outside-platform.md) | Деньги за услуги мимо платформы; IPS QR как помощник оплаты (v1); эскроу — после юриста и PSP | принято, сроки уточнены ADR-0018 |
| [0018](0018-mvp-scope-anonymous-no-payments.md) | Границы MVP: без юрлица, платежей и формальных правовых механизмов; всё перенесённое — в v1, архитектурный задел сохраняется | принято |
| [0019](0019-goods-section-module-deferred.md) | Раздел «Вещи» — модуль `goods` монолита (17-й), не микросервис; стадии «Вещи-0» → пилот «Вещи-lite» → «Раздел» по точкам решения; в MVP — только заглушка S58 | принято, реализация отложена до итерации «Вещи» |
| [0020](0020-code-patterns-and-consistency.md) | Паттерны кода и единообразие: один шаблон модуля, порты и адаптеры, Unit of Work, Repository (Data Mapper), синглтоны только через DI (dishka `APP`), единая модель ошибок, контроль в CI | принято |

## Шаблон

```markdown
# ADR-NNNN: <решение одной фразой>

- **Статус:** предложено | принято | заменено ADR-XXXX | отменено
- **Дата:** YYYY-MM-DD
- **Связанные документы:** …

## Контекст
## Рассмотренные варианты
## Решение
## Последствия
```

Каждый раздел «Последствия» состоит из трёх частей: **положительные**, **отрицательные и риски**, **что сделать**.
