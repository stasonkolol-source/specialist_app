# Откат релиза

Релиз backend — `kamal deploy -d production` с pre-deploy `alembic upgrade head`; Mini App —
`wrangler deploy` (ARCHITECTURE §16.4). Миграции только expand/contract: каждая совместима с
предыдущей версией приложения, поэтому откат кода не требует отката схемы.

> Прогон «на сухую» — `kamal rollback` на stage в 3.1 и на проде в 3.1b (DEVELOPMENT_PLAN).

## 1. Решить за 5 минут

Откатываем, если после релиза: всплеск 5xx, p95 API > 400 мс дольше 10 минут, не входит Mini App,
ломается отправка уведомлений, ошибки webhook. Чинить «вперёд» — только если причина понятна и
правка меньше 15 минут.

Записать в канал инцидента: версию релиза, время, симптом, кто ведёт.

## 2. Backend

```bash
kamal app containers -d production   # версии (sha образа), которые ещё на сервере
kamal rollback <предыдущий sha> -d production
```

- kamal-proxy переключает трафик без простоя; `/up` должен ответить 200.
- Схему БД **не откатываем**: прошлая версия кода работает с новой схемой (expand/contract).
  Если миграция сама сломала данные — [restore.md](restore.md) (PITR на момент до миграции).
- Миграция, которая нарушила expand/contract (удалила колонку, которую читает прошлая версия),
  — исключение: остановить запись (`platform.maintenance`), написать обратную миграцию, выкатить.

## 3. Mini App

```bash
cd apps/tma
pnpm exec wrangler deployments list --env production
pnpm exec wrangler rollback <deployment-id> --env production
```

Старые чанки остаются в кэше клиентов (`/assets/*` immutable): откат HTML достаточно. Если новый
клиент требует новый API, а API откатили, — поднять `min_versions` в client-config нельзя (это
заставит обновиться на сломанную версию); откатывать фронт вместе с backend.

## 4. После отката

1. Проверить: `/up`, вход в Mini App, лента, отправка сообщения, уведомление в бота.
2. Заблокировать повторный релиз той же версии: issue с меткой `release-blocker`.
3. Разбор в `docs/incidents/`: что сломалось, почему не поймали тесты, какой тест добавили.
