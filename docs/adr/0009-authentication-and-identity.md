# ADR-0009: Аутентификация и модель идентичности

- **Статус:** принято
- **Сроки уточнены** [ADR-0018](0018-mvp-scope-anonymous-no-payments.md): в MVP телефон добровольный (бейдж), согласия — правила площадки, политика конфиденциальности и 18+.
- **Дата:** 2026-09-26
- **Связанные документы:** [research/02-telegram-platform.md §3](../research/02-telegram-platform.md#3-аутентификация), [research/04-frontend-and-mobile.md](../research/04-frontend-and-mobile.md), [ARCHITECTURE.md §8.2](../ARCHITECTURE.md#82-аутентификация-и-сессии), [ADR-0003](0003-api-first-rest-openapi.md)

## Контекст

- **Этап 1.** Пользователи приходят только из Telegram: Mini App получает подписанный `initData`, бот — апдейты с `from.id`.
- **Этап 2.** Появятся нативные iOS- и Android-приложения. App Store (правило 4.8) требует: если есть вход через сторонний сервис (Telegram), нужен равноценный приватный вариант, на практике Sign in with Apple.
- **Связь аккаунтов.** Один и тот же человек должен видеть свои заявки, отзывы и подписку и в Telegram, и в iOS.
- **Что появилось у Telegram в 2026 году:**
  - OpenID Connect с 2026-03-01 (`oauth.telegram.org`, Authorization Code + PKCE, scopes `openid profile phone telegram:bot_access`);
  - нативные SDK входа для iOS и Android с апреля 2026.
- **Санкции.** Пользователя можно ограничить (баны, запрет публиковать); ограничение должно действовать быстро.

## Рассмотренные варианты

1. **Проверять `initData` на каждом запросе** без собственных сессий. Минусы: `initData` большой, это bearer-секрет со сроком до часов, мобильным клиентам он недоступен. Отвергнут.
2. **Серверные сессии в cookies.** Минусы: в WebView Telegram Web (iframe) third-party cookies могут блокироваться **[Допущение: research/02 §2.8]**, для мобильного API неудобно. Отвергнут.
3. **Обмен `initData` на собственные токены: короткий JWT + ротируемый refresh; модель `users` + `auth_identities`.** Выбран.

## Решение

**Модель.**
- `identity.users` — человек.
- `identity.auth_identities(provider, subject)` — способ входа, уникальный по паре. Провайдеры: `telegram` (этап 1); `apple`, `google`, `phone` (этап 2); `email` — резерв.
- «Клиент» и «исполнитель» — не роли, а возможности аккаунта. Роли есть только у персонала (`admin`, `moderator`, `support`).

**Вход из Mini App.**
1. Клиент вызывает `POST /api/v1/auth/telegram`, передавая `initData` целиком (заголовок `Authorization: tma <initData>`).
2. Сервер проверяет подпись: `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`, `hash` сверяется в constant time. Поля из `initDataUnsafe` не доверяем.
3. `auth_date` должен быть не старше **1 часа**, допуск расхождения часов — 60 с. Проверяем сами: `aiogram.utils.web_app` проверяет только подпись. `initData` никогда не логируем.
4. Upsert `users` и `auth_identities(provider='telegram', subject=<tg id>)`, снимок профиля (username, имя, `language_code`, `photo_url`, `allows_write_to_pm`).
5. Выдаём:
   - **access** — JWT на 15 минут, EdDSA/ES256, ключи с `kid` и ротацией; клеймы `sub` (наш `user_id`), `sid` (сессия), `plat` (tma/ios/android/web/admin), `amr=["tg_webapp"]`, `tl` (уровень доверия, [ADR-0016](0016-trust-safety-and-reviews.md)), `roles` (только у персонала);
   - **refresh** — opaque 256 бит; в БД хранится только SHA-256; ротация при каждом использовании. Повторное использование старого токена отзывает всю цепочку сессий.
6. **Хранение на клиенте.**
   - В Mini App оба токена живут **только в памяти**. Refresh нужен, чтобы продлевать сессию, пока приложение открыто или свёрнуто дольше часа. При каждом новом запуске — новый обмен свежего `initData`, персистентное хранилище не нужно.
   - В мобильном приложении refresh хранится в Keychain/Keystore.
   - Cookies не используем.
7. **Отдельный бот и токен на каждое окружение** (dev/stage/prod); `bot_id` хранится в сессии.

**Бот.** Апдейты приходят на webhook с заголовком `X-Telegram-Bot-Api-Secret-Token`. Пользователь определяется по `from.id` → `auth_identities`; первый `/start` создаёт аккаунт тем же сервисом, что и Mini App.

**Телефон.**
- В Telegram — `requestContact`. Контакт приходит боту; принимаем его, только если `contact.user_id == from.id`, и записываем как подтверждённый. В MVP телефон **добровольный**: даёт бейдж «Телефон подтверждён» и уровень доверия 1 ([ADR-0016](0016-trust-safety-and-reviews.md), [ADR-0018](0018-mvp-scope-anonymous-no-payments.md)).
- На этапе 2 — OIDC scope `phone` или OTP через Telegram Gateway ($0,01 за доставленный код) с SMS-fallback для людей без Telegram.

**Этап 2 (App Store / Google Play).**

| Вход | Реализация |
|---|---|
| «Войти через Telegram» | Официальный native SDK (OIDC). Обмен кода — на backend (discovery требует client secret). Связь с аккаунтом Mini App — по claim **`id`** из scope `profile`, а не по `sub`. **[Допущение]**: `id` совпадает с `user.id` из Bot API — проверить на тестовом аккаунте до реализации |
| Sign in with Apple | Обязателен в iOS рядом со входом через Telegram (правило 4.8). Проверка `identity_token` по JWKS Apple через joserfc |
| Google Sign-In | Android |
| Телефон + OTP | Для пользователей без Telegram |

**Привязка и слияние аккаунтов.** Второй способ входа привязывается из настроек через тот же OIDC-поток или через fallback `t.me/<bot>?start=link_<nonce>`. Если identity уже принадлежит другому аккаунту — сценарий слияния:
- слияние только после подтверждения обоих способов входа;
- сущности переносятся на выживший аккаунт;
- всё фиксируется в аудите.

**Ограничения и отзыв.**
- Санкции хранятся в `identity.restrictions` (kind `posting_blocked`, `responding_blocked`, `messaging_blocked`, `shadow_banned`, `suspended`, `banned`). `identity.users.status` принимает только значения `active` и `deleted`: приостановки и баны — это записи `restrictions`, а не статус аккаунта. Проверка «можно ли» — в application-сервисах, ответ API `403` с `code: "restricted"`.
- Бан отзывает все refresh-сессии, а `sid` попадает в denylist Valkey на время жизни access-токена (≤15 мин).

**Персонал.** SQLAdmin смонтирован на `/admin` в процессе `web` и публикуется как `admin.<domain>` за Cloudflare Access. Вход:
- отдельная аутентификация: argon2-пароль + TOTP, либо Telegram-вход с проверкой роли;
- доступ из закрытой сети (Cloudflare Access или VPN);
- все действия — в `platform.audit_log`.

## Последствия

**Положительные**

- Мобильное приложение подключается к тем же `sessions` и `auth_identities` без изменения доменной модели.
- Бан или отзыв сессии срабатывает в пределах 15 минут, а при denylist — сразу.
- `initData` живёт на сервере секунды: только в момент обмена.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| Утечка строки `initData` даёт вход в пределах окна 1 ч | HTTPS, короткое окно, rate limit на `/auth/telegram`, `initData` не логируем |
| Слияние аккаунтов — сложный сценарий | Реализуем к этапу 2, покрываем тестами; до этого привязка разрешена только к «чистым» identity |
| OIDC Telegram молодой (с марта 2026), переключение бота в OIDC-режим в BotFather, по отзывам, необратимо | Сначала проверяем на отдельном боте |

**Что сделать**

- Утилита проверки `initData` с тестами на эталонных векторах (включая просроченный `auth_date` и подмену поля).
- Ротация ключей JWT (JWKS-эндпоинт для внутренних сервисов не нужен, но `kid` — с первого дня).
- Rate limit: `/auth/*` — 10 запросов в минуту на IP и 30 в час на Telegram-пользователя.
