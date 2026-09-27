# ADR-0012: Фронтенд — React + Vite для Mini App и веба, общий TypeScript-core в монорепо, Expo на этапе 2

- **Статус:** принято
- **Дата:** 2026-09-26
- **Связанные документы:** [research/04-frontend-and-mobile.md](../research/04-frontend-and-mobile.md), [research/02-telegram-platform.md](../research/02-telegram-platform.md), [ADR-0003](0003-api-first-rest-openapi.md), [ADR-0009](0009-authentication-and-identity.md)

## Контекст

- **Этап 1** — Telegram Mini App: веб-приложение в WebView Telegram на iOS, Android, Desktop и Web.
- **Этап 2** — нативные iOS/Android. Хочется переиспользовать максимум кода, но без ущерба старту и «телеграмности» Mini App.
- **Особенности WebView:**
  - Mini App открывают «на секунду», поэтому холодный старт критичен;
  - тема задаётся CSS-переменными Telegram;
  - навигацию ведут нативные BackButton/MainButton;
  - вертикальный свайп сворачивает приложение;
  - с 2026-07-20 методы Mini App работают только на исходном origin.
- **Команда:** 1–2 человека, в том числе на фронтенде.
- **Местные сербы** вероятно реже пользуются Telegram. Веб-версия каталога, открываемая по ссылке из Viber или WhatsApp, расширяет охват.

## Рассмотренные варианты

| Вариант | Переиспользование с native | Риски |
|---|---|---|
| **React + Vite (SPA) с Telegram-адаптером; Expo на этапе 2; общий core** | Высокое: API-клиент, Zod-схемы, домен, хуки, i18n, токены, deep links. UI пишется дважды | Два UI-слоя |
| Vue или Svelte + Capacitor на этапе 2 | Максимальное (тот же веб) | Риск отказа по 4.2 («repackaged website»), потолок UX |
| «Одна кодовая база» на React Native Web / Expo web / Tamagui | UI тоже общий | +75 KB gz к старту, потеря нативного вида Telegram, сложнее чинить WebView; карты, медиа, вход и платежи всё равно разные |
| Flutter (веб + native) | Почти ноль для Mini App | Flutter Web не подходит для text-rich интерфейсов; второй язык |

## Решение

**Mini App и веб (этап 1).** Версии на 2026-09-26:

| Слой | Выбор |
|---|---|
| База | React 19 (одна версия на весь workspace, на этапе 2 — та, что пинит Expo SDK), TypeScript 6.0 (тулинг ещё не поддерживает 7.x), Vite 8 |
| Интеграция с Telegram | `@tma.js/sdk-react` 3.x за собственным пакетом `platform`. Экраны не импортируют Telegram SDK напрямую. Функции новее, чем покрывает SDK (например, `requestChat` из Bot API 9.6), вызываются через низкоуровневый bridge tma.js (`postEvent`), как рекомендует research/04; официальный `telegram-web-app.js` — запасной вариант |
| Роутинг | TanStack Router. Launch params забираем из `location.hash` до инициализации роутера; в Telegram-оболочке — memory/hash history, в веб-оболочке — browser history |
| Данные | TanStack Query + клиент, сгенерированный **orval** из OpenAPI (хуки, Zod-схемы, MSW-моки) |
| Формы | React Hook Form + Zod |
| Состояние | Zustand (только UI-состояние; серверное — в Query) |
| i18n | i18next с ICU. Локали MVP — `ru`, `sr-Latn`, `sr-Cyrl`; `en` — v1. Исходник сербских строк — кириллица, латиница генерируется ([ADR-0013](0013-i18n-multilingual-content.md)) |
| UI | Tailwind CSS 4 + собственные компоненты на семантических токенах, которые мапятся на `--tg-theme-*`. TelegramUI не используем как основу: не обновлялся с 2025-10, peer React 18 |
| Медиа | Сжатие фото на клиенте (canvas, ≈2048 px); видео — multipart upload в S3 (Uppy `@uppy/aws-s3`); EXIF на клиенте не доверяем, сервер удаляет его всегда |
| Карты | Leaflet, загружается лениво (выбор точки, показ района); MapLibre GL — когда карта станет ключевым экраном. Тайлы — OpenFreeMap или Protomaps на R2 |
| Наблюдаемость | `@sentry/react`. Продуктовая аналитика — серверная по умолчанию; клиентский SDK (PostHog EU) — только после согласия (ст. 160 ZEK) |
| Тесты | Vitest, Playwright (e2e в браузерной оболочке), MSW |
| Сборка и хостинг | Cloudflare Workers Static Assets на `app.<domain>`. Хэшированные ассеты — `immutable`, `index.html` — `no-cache`. `build.target` понижен под Telegram iOS; минимальная поддерживаемая версия iOS решается по аналитике (открытый вопрос) |
| Бюджет первого экрана | ≤ 200 KB gz JS **[Допущение: рекомендация research/04, не норматив]**; карта, загрузчик медиа и редактор прайса грузятся лениво |

**Работа с API.** Mini App обращается к API по тому же origin (`app.<domain>/api/*` проксируется Cloudflare на backend), поэтому нет CORS и preflight-запросов. Правило Bot API 10.2 касается только вызовов методов `Telegram.WebApp.*`; им достаточно того, что весь SPA живёт на `app.<domain>`. Мобильные клиенты используют `api.<domain>`. Авторизация — bearer-токены, без cookies.

**Одна сборка — две оболочки.** SPA собирается один раз:
- **Telegram-оболочка:** реализация `platform` через tma.js — MainButton, BackButton, haptics, `shareMessage`, `requestWriteAccess`.
- **Браузерная оболочка:** гостевой просмотр каталога, профилей и заявок по ссылкам, страница удаления аккаунта (требование Google Play), fallback для deep links. Полноценный веб-вход (Telegram OIDC, телефон) — v1.

**Монорепо** — pnpm workspaces + Turborepo:

```text
apps/tma            # Mini App + веб-оболочка (React + Vite)
apps/mobile         # этап 2: Expo (iOS/Android)
packages/api-client # orval: типы, fetchers, Query hooks, Zod-схемы, MSW-моки
packages/domain     # бизнес-правила без DOM/RN: статусы, форматирование RSD и дат
packages/hooks      # headless-хуки сценариев
packages/platform   # интерфейсы: auth, storage, nav buttons, haptics, share, location, push
packages/i18n       # ресурсы, транслитерация, форматтеры
packages/design-tokens
packages/links      # схема deep links: канонический URL ↔ startapp ↔ universal link
packages/ui-web     # веб-компоненты
```

**Этап 2 — Expo** (SDK 57 — текущая стабильная; 58 — после релиза):
- Expo Router, EAS Build/Submit/Update, FlashList, MMKV;
- `expo-apple-authentication`, Telegram Login SDK (OIDC), `expo-notifications`;
- IAP через `expo-iap` или RevenueCat;
- переиспользуются все `packages/*`, кроме `ui-web`.

**Пересмотр решения.** Решение об «одной кодовой базе» на React Native Web пересматривается, если одновременно:
- native нужен в пределах 3–4 месяцев после запуска Mini App;
- у команды есть опыт RN;
- владелец готов к менее «телеграмному» виду Mini App.

## Последствия

**Положительные**

- Быстрый старт Mini App, нативный для Telegram вид (тема, кнопки, haptics).
- Бизнес-логика клиента, API-контракт и тексты пишутся один раз и переходят в Expo без переписывания.
- Веб-оболочка без дополнительной работы даёт гостевой доступ, SEO-страницы (v1) и страницу удаления аккаунта.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| Два UI-слоя (веб и RN) | Headless-хуки и токены минимизируют дублирование. UI native всё равно должен быть нативным (App Store 4.2) |
| SDK отстают от Bot API (tma.js покрывает до 9.5 при текущей 10.3) | Изоляция за `platform`; прямые вызовы официального скрипта для новых методов |
| Различия WebView (загрузка файлов на Android, пикеры даты на Linux, старые iOS) | Матрица ручного тестирования, свои пикеры, fallback-пути, `isVersionAtLeast` |
| Pull-to-refresh конфликтует с жестом сворачивания Mini App | Обновление кнопкой и при возврате фокуса |

**Что сделать**

- Настроить генерацию `api-client` в CI из `openapi.json` backend. Сборка падает при несовпадении типов.
- Сделать дизайн-систему на токенах с маппингом на тему Telegram и собственной палитрой для веба и native.
- Провести ручной UX-аудит 5–10 Mini Apps из вкладки Apps перед дизайном.
