# OWASP ASVS 4.0.3, уровень 2 — чек-лист API «Соседей»

Цель — ASVS L2 для API ([ARCHITECTURE §13.1](../ARCHITECTURE.md#131-модель-угроз-кратко), §2.4).
Проход сделан в шаге 8.4 (2026-10-04) по коду `main` + ветки 8.4. Здесь только требования,
применимые к нашей архитектуре: вход через Telegram `initData` → собственные токены, без паролей
пользователей и cookies, JSON API за Cloudflare и kamal-proxy, Mini App на Cloudflare Workers.

Статусы: **✅** выполнено (доказательство — ссылка); **⚠️** частично или закрывается инфраструктурой
(шаг указан); **⏳** запланировано шагом плана; **N/A** — не применимо (почему).

Проверка: `make audit`; `uv run pytest -k authz` (или `-m authz` — только тесты «чужой ресурс»,
integration); этот чек-лист.

Пути ниже — от корня репозитория; `be/` = `backend/src/app/`.

## V1. Архитектура и модель угроз

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 1.1.2 | Модель угроз для изменений | ✅ | ARCHITECTURE §13.1; ADR в `docs/adr/` |
| 1.1.4 | Границы доверия и компоненты описаны | ✅ | ARCHITECTURE §3, §16.3 (Cloudflare → kamal-proxy → web) |
| 1.2.3 | Один проверенный механизм аутентификации | ✅ | ADR-0009; `be/platform/security/` (initData, JWT, refresh) |
| 1.4.1 | Проверки доступа — на доверенной стороне | ✅ | владение — в use case и политиках модулей (`jobs/domain/policies.py`), §13.2 |
| 1.4.4 | Единый механизм контроля доступа | ✅ | principal из JWT (`be/platform/http/security.py`), политики модулей; [отчёт authz](#отчёт-покрытия-тестов-прав) |
| 1.5.3 | Валидация входа на доверенной стороне | ✅ | pydantic-схемы роутеров, доменные инварианты |
| 1.6.1 | Политика управления ключами | ⚠️ | правила в OWNER_CHECKLIST «Правила обращения с секретами»; [secrets-rotation.md](../../infra/runbooks/secrets-rotation.md); SOPS/Kamal — 3.1b–3.1c |
| 1.7.1 | Единый формат логов | ✅ | structlog JSON, `be/platform/observability/logging.py` |
| 1.8.1 | Чувствительные данные определены и классифицированы | ✅ | ARCHITECTURE §13.4, §7.10 |
| 1.9.1 | Шифрование связи между компонентами | ⚠️ | Cloudflare → origin TLS (Full strict) и private network Hetzner — 3.1a–3.1c |
| 1.10.1 | Контроль версий исходников, ревью | ✅ | GitHub, PR + CI, `.github/pull_request_template.md` |
| 1.11.1 | Бизнес-потоки описаны | ✅ | ARCHITECTURE §7.9 (state machines) |
| 1.12.2 | Загруженные файлы не исполняются и отдаются отдельно | ✅ | ADR-0007: изолированный бакет, CDN-домен отдельно от API |
| 1.14.1 | Разделение компонентов по уровню доверия | ✅ | web / worker / worker-media / bot — отдельные процессы; БД в private network |
| 1.14.6 | Нет небезопасных клиентских технологий | ✅ | без Flash/ActiveX/NPAPI; Mini App — React |

## V2. Аутентификация

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 2.1.x | Пароли пользователей | N/A | паролей у пользователей нет: вход — подписанный Telegram `initData` (ADR-0009) |
| 2.2.1 | Защита от перебора и автоматизации | ✅ | `POST /auth/*` — 10/мин на IP и 30/ч на пользователя (§13.3); IP — по [ClientAddressMiddleware](../../backend/src/app/interfaces/http/proxy.py), подделка X-Forwarded-For больше не обходит лимит (8.4) |
| 2.2.2 | Слабые аутентификаторы только как второй фактор | N/A | SMS/e-mail для входа не используются |
| 2.5.x | Восстановление учётной записи | N/A | доступ = Telegram-аккаунт; без своих учётных данных |
| 2.8.x | TOTP персонала | ⏳ | вход персонала argon2 + TOTP — 2.7a; админка за Cloudflare Access — 2.7b, 3.1c |
| 2.9.1 | Криптографическая проверка аутентификатора | ✅ | `be/platform/security/initdata.py`: HMAC-SHA256, constant-time, `auth_date` ≤ 1 ч; тесты `tests/unit/platform/security/test_initdata.py` |
| 2.10.1 | Нет зашитых секретов сервисов | ✅ | `SecretStr` в настройках; gitleaks в CI (`ci-backend.yml`) и pre-commit |
| 2.10.4 | Секреты не в исходниках | ✅ | `.env` вне git, `backend/.env.example` без значений (тест полноты) |

## V3. Сессии

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 3.1.1 | Токены не в URL | ✅ | `Authorization: Bearer`; `initData` — в заголовке `Authorization: tma …` |
| 3.2.1 | Новый токен при входе | ✅ | `be/modules/identity/` — новая сессия на каждый обмен initData |
| 3.2.2 | ≥ 64 бит энтропии | ✅ | refresh — `secrets`, `be/platform/security/refresh.py` |
| 3.2.3 | Токены в браузере — безопасно | ✅ | Mini App хранит токены только в памяти (`packages/api-client/src/mutator.ts`); localStorage — только публичные справочники (`apps/tma/src/app/persist.ts`) |
| 3.3.1 | Выход и истечение делают токен недействительным | ✅ | отзыв сессии + denylist `sid` в Valkey (`be/platform/security/denylist.py`); access 15 мин |
| 3.3.2 | Повторная аутентификация по времени | ✅ | refresh Mini App 7 дней, мобильный — 30 (JWT_REFRESH_TTL_*) |
| 3.3.4 | Пользователь видит и завершает сессии | ⏳ | список устройств — v1; бан/удаление отзывают все сессии |
| 3.5.1 | Отзыв OAuth/refresh | ✅ | ротация refresh с детектором повторного использования (`identity/domain/session.py`, аудит `auth.refresh.reused`) |
| 3.5.3 | Подпись токенов проверяется, алгоритм фиксирован | ✅ | EdDSA (Ed25519) с `kid`, `be/platform/security/jwt.py`; тесты `test_jwt.py` |
| 3.4.x, 3.6.x | Cookies, федеративный выход | N/A | cookies не используются; IdP один — Telegram |

## V4. Контроль доступа

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 4.1.1 | Проверки на сервере | ✅ | use case и политики модулей |
| 4.1.2 | Атрибуты доступа не подделать | ✅ | `user_id`, `tl`, `sid` — из подписанного JWT |
| 4.1.3 | Минимальные привилегии | ✅ | роли персонала только в admin API (§13.2) |
| 4.1.5 | Отказ — безопасно | ✅ | чужой ресурс → 404 (не раскрываем существование); RFC 9457 без деталей |
| 4.2.1 | IDOR | ✅ | [отчёт покрытия](#отчёт-покрытия-тестов-прав): 57 операций с id классифицированы, у 42 владельческих и 4 смешанных — тест «чужой ресурс» |
| 4.2.2 | CSRF | ✅ | только Bearer в заголовке, cookies нет — CSRF неприменим; CORS не включён (тот же origin) |
| 4.3.1 | MFA для админки | ⏳ | TOTP персонала — 2.7a, Cloudflare Access — 2.7b, 3.1c |
| 4.3.3 | Доступ персонала к ПД журналируется | ✅ | `platform.audit_log` (`be/platform/audit/`), выгрузка — `privacy.user_data.exported` |

## V5. Валидация, санитизация, кодирование

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 5.1.1 | HTTP parameter pollution | ✅ | FastAPI/pydantic: строгие типы параметров |
| 5.1.3 | Позитивная валидация входа | ✅ | pydantic-схемы, enum, `max_length`; 422 со списком полей |
| 5.1.4 | Структурированные данные строго типизированы | ✅ | OpenAPI 3.1 `backend/openapi.json`, schemathesis (`backend/tests/contract/`) |
| 5.2.1 | HTML от пользователя санитизируется | ✅ | сообщения бота — `html.escape` (`be/platform/telegram/texts.py`); Mini App — React экранирует |
| 5.2.6 | SSRF | ✅ | сервер не ходит по URL пользователя; медиа — presigned PUT в R2 |
| 5.3.4 | SQL — параметризованно | ✅ | SQLAlchemy, `text()` с параметрами; FTS — `websearch_to_tsquery` (`be/modules/search/infrastructure/search.py`) |
| 5.3.3 | Контекстное экранирование (XSS) | ✅ | React; CSP Mini App без `unsafe-*` (`apps/tma/src/app/csp.ts`, e2e `app.spec.ts`) |
| 5.5.2 | Без небезопасной десериализации | ✅ | только JSON; pickle и YAML от пользователя не читаются |

## V6. Криптография хранения

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 6.2.1 | Модули падают безопасно | ✅ | `cryptography`, ошибки → 401 без деталей |
| 6.2.2 | Проверенные алгоритмы | ✅ | Ed25519, HMAC-SHA256, SHA-256; хэши удалённых — HMAC с `APP_HASH_KEY` |
| 6.3.1 | Криптостойкий ГСЧ | ✅ | `secrets`, UUIDv7 (`be/platform/kernel/ids.py`) |
| 6.4.1 | Секреты в хранилище секретов | ⚠️ | dev — `.env` вне git; stage/prod — SOPS + Kamal (3.1b–3.1c) |
| 6.4.2 | Ключи не раскрываются приложению сверх нужного | ✅ | процесс получает только свои переменные (Kamal roles) — проверить в 3.1c |

## V7. Ошибки и журналы

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 7.1.1 | Нет учётных данных и токенов в логах | ✅ | процессор маскирования `be/platform/observability/masking.py` — в structlog, stdlib-логах и Sentry; тесты `tests/unit/platform/test_masking.py` (токены бота, JWT, Bearer, initData, секрет webhook) |
| 7.1.2 | Нет ПД в логах | ✅ | ключи `phone`, `text`, `email`, адреса клиента, `init_data` скрываются целиком, телефоны и длинные цифры — по шаблону; access-лог без query string; SDK AI не ниже INFO; выборочная ревизия вызовов `log.*` (8.4) — ПД не логируется |
| 7.1.3 | События безопасности журналируются | ✅ | access-лог со статусом (401/403/429) и `request_id`; `auth.refresh.reused` и действия персонала — `platform.audit_log` |
| 7.1.4 | Контекст для расследования | ✅ | `request_id`, `trace_id`, `user_id` (внутренний UUID) |
| 7.3.1 | Защита от инъекций в логи | ✅ | JSON-рендерер; X-Request-ID только `[A-Za-z0-9._-]{1,64}` (`be/interfaces/http/middleware.py`) |
| 7.3.3 | Журналы защищены | ⚠️ | Grafana Cloud 14 дней, журналы безопасности 12 мес в объектном хранилище — 3.3 |
| 7.4.1 | Общее сообщение об ошибке с id | ✅ | 500 → RFC 9457 без деталей + `trace_id` (`tests/unit/interfaces/test_http.py`) |

## V8. Защита данных

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 8.1.1 | Кэши сервера не хранят ПД | ✅ | Cloudflare не кэширует `/api`; публичные справочники — отдельные ETag-ответы |
| 8.2.1 | Заголовки против кэширования ПД | ✅ | ответ на запрос с Authorization без своей политики — `Cache-Control: no-store` (с ETag — `private, no-cache`), `be/interfaces/http/security_headers.py` (8.4) |
| 8.2.2 | В хранилище браузера нет ПД | ✅ | см. 3.2.3; черновик заявки — DeviceStorage Telegram на устройстве пользователя |
| 8.3.1 | ПД в теле или заголовках, не в query | ✅ | initData и токены — заголовки; id в путях — UUIDv7 |
| 8.3.2 | Удаление и экспорт данных | ✅ | `POST /me/deletion` (2.12a), выгрузка — [data-export.md](../../infra/runbooks/data-export.md), [deletion-request.md](../../infra/runbooks/deletion-request.md) |
| 8.3.4 | Чувствительные данные определены | ✅ | ARCHITECTURE §13.4; адрес и телефон скрыты до выбора (`tests/integration/test_contacts_privacy.py`) |
| 8.3.5 | Доступ к ПД журналируется | ✅ | `platform.audit_log` |
| 8.3.8 | Сроки хранения исполняются | ✅ | `platform.retention_sweep` (2.12b), матрица §7.10 |

## V9. Связь

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 9.1.1 | TLS для всех соединений клиента | ⚠️ | Cloudflare (TLS 1.2+, HSTS на краю) — 3.1c; приложение ставит HSTS на HTTPS-ответы (8.4) |
| 9.2.2 | TLS к внешним сервисам | ✅ | Telegram, R2, OpenAI, Anthropic, Sentry — HTTPS |
| 9.2.x | TLS до БД и Valkey | ⚠️ | private network Hetzner без выхода наружу — 3.1a–3.1b (решение ADR-0015) |

## V10. Вредоносный код

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 10.3.2 | Зависимости зафиксированы и проверяются | ✅ | `uv.lock`, `pnpm-lock.yaml`; Dependabot; `pip-audit` и `pnpm audit` (`.github/workflows/audit.yml`) |
| 10.3.3 | Защита от захвата поддоменов | ⚠️ | DNS — Terraform (3.1a), без висящих CNAME |

## V11. Бизнес-логика

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 11.1.1 | Последовательность шагов соблюдается | ✅ | state machines заявки, отклика, сделки, спора (§7.9) |
| 11.1.2 | Лимиты скорости бизнес-операций | ✅ | §13.3: заявки, отклики, сообщения, загрузки, жалобы; 429 + `Retry-After` |
| 11.1.4 | Антиавтоматизация | ✅ | лимиты по пользователю и по настоящему IP (8.4); грубые IP-лимиты — Cloudflare |
| 11.1.6 | Гонки (TOCTOU) | ✅ | optimistic locking (`If-Match`, `version`), `SELECT … FOR UPDATE`, идемпотентность (`be/platform/idempotency/`) |

## V12. Файлы

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 12.1.1 | Лимиты размера | ✅ | `be/modules/media/domain/policy.py` |
| 12.1.2 | Защита от «бомб» | ✅ | лимит разрешения при декодировании (`be/modules/media/infrastructure/imaging.py`) |
| 12.2.1 | Тип проверяется по содержимому | ✅ | magic bytes в обработке, allow-list MIME |
| 12.3.1 | Пути не из пользовательского ввода | ✅ | ключи объектов строит сервер (`purpose/YYYY/MM/<uuid>/…`) |
| 12.4.1 | Файлы вне веб-корня приложения | ✅ | приватный бакет R2, отдача — CDN вариантов |
| 12.5.2 | Загруженное не исполняется как HTML | ✅ | раздаются только перекодированные WebP/MP4 вариантов; EXIF удаляется |

## V13. API

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 13.1.1 | Единая кодировка и парсеры | ✅ | JSON UTF-8 |
| 13.1.3 | URL без чувствительных данных | ✅ | см. 8.3.1 |
| 13.1.4 | Авторизация на уровне URI и ресурса | ✅ | `AUTHENTICATED` в роутерах + владение в use case |
| 13.2.1 | Разрешены только нужные методы | ✅ | 405 с `Allow` (`tests/unit/interfaces/test_http.py`) |
| 13.2.2 | Валидация схемы JSON | ✅ | pydantic; schemathesis по OpenAPI (`make contract`) |
| 13.2.3 | Защита от CSRF | ✅ | см. 4.2.2 |
| 13.2.5 | Проверка Content-Type | ✅ | тело — только JSON; битый JSON → 400 |

## V14. Конфигурация

| ID | Требование | Статус | Доказательство |
|---|---|---|---|
| 14.1.1 | Повторяемая сборка | ✅ | образ по digest, `images.yml`, lock-файлы |
| 14.2.1 | Компоненты обновлены, без известных уязвимостей | ⚠️ | pip-audit: 0; pnpm audit: 1 high — braces GHSA-vfj7-8cjw-p6xm, только линтер (`packages/config` → eslint-plugin-boundaries → micromatch), в бандл не попадает; исправленной версии нет — решение владельца |
| 14.2.2 | Лишнее выключено | ✅ | `/api/v1/docs` и `openapi.json` выключены в prod (`be/interfaces/http/app.py`) |
| 14.3.2 | Отладка выключена в prod | ✅ | без `debug`, без трассировок в ответах |
| 14.3.3 | Версия сервера не раскрывается | ✅ | `server_header=False` у uvicorn (8.4) |
| 14.4.1 | Content-Type с кодировкой | ✅ | JSON-ответы FastAPI |
| 14.4.2 | `Content-Disposition: attachment` у API | ⚠️ | не ставим: компенсируют CSP `default-src 'none'` и `nosniff` — ответ API не исполняется и не рендерится |
| 14.4.3 | CSP | ✅ | API: `default-src 'none'; frame-ancestors 'none'` (8.4); Mini App: строгая CSP без `unsafe-*` (`apps/tma/src/app/csp.ts`, `_headers`) |
| 14.4.4 | `X-Content-Type-Options: nosniff` | ✅ | API и Mini App (8.4) |
| 14.4.5 | HSTS | ✅ | на HTTPS-ответах API; на краю Cloudflare — 3.1c |
| 14.4.6 | Referrer-Policy | ✅ | API `no-referrer`, Mini App `strict-origin-when-cross-origin` (8.4) |
| 14.4.7 | Запрет встраивания | ✅ | API — `frame-ancestors 'none'` + `X-Frame-Options: DENY`; Mini App — только `web.telegram.org` |
| 14.5.1 | Только нужные методы | ✅ | см. 13.2.1 |
| 14.5.3 | CORS не доверяет `null` и всем | ✅ | CORS не включён: Mini App и API на одном origin |
| 14.5.4 | Заголовки прокси аутентифицированы | ✅ | X-Forwarded-For/Proto принимаются только от своих прокси, CF-Connecting-IP — только от края Cloudflare (`be/interfaces/http/proxy.py`, `tests/unit/interfaces/test_http_security.py`) (8.4) |

## Отчёт покрытия тестов прав

Источник истины — [`backend/tests/architecture/test_authz_coverage.py`](../../backend/tests/architecture/test_authz_coverage.py):
каждая операция API с id ресурса в пути (57 на 2026-10-04) отнесена к `owner` (42), `mixed` (4),
`actor` (7) или `public` (4). Для `owner` и `mixed` указан тест, где другой пользователь получает
404 (ответ на чужой отзыв — 403), и тест помечен `@pytest.mark.authz`; архитектурный тест падает,
если операция без классификации или тест без маркера. В 8.4 добавлены проверки 16 операций, у
которых их не было (сделка: подтверждение, отклонение, завершение, отзыв; спор: ответ и отзыв
посторонним; отклик: правка, выбор, «в избранные»; приглашения заявки; правка подписки; контакт в
чужой диалог; прайс и портфолио). Настоящих дыр не найдено: владение проверялось в use case.

## Вне кода (инфраструктура и владелец)

| Что | Где закрывается |
|---|---|
| Админка за Cloudflare Access + TOTP персонала | 2.7a, 2.7b, 3.1c |
| SSH только по ключу, firewall Hetzner: 443 только с диапазонов Cloudflare, БД — только private network | 3.1a, 3.1b (Terraform) |
| Authenticated Origin Pulls (mTLS Cloudflare → origin) — чтобы чужой аккаунт Cloudflare не ходил на origin с поддельным CF-Connecting-IP | 3.1c, рекомендация 8.4 |
| Webhook бота с `secret_token`, узкий `allowed_updates` | 0.25e (webhook в web) |
| Ротация всего, что прошло через чат | K43, [secrets-rotation.md](../../infra/runbooks/secrets-rotation.md) |
| Прогон runbooks «на сухую» | [infra/runbooks](../../infra/runbooks/README.md) |
| Сверка политики конфиденциальности с включёнными обработчиками | 8.4, перед 8.5 |
