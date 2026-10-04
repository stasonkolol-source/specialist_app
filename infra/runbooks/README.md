# Runbooks

Порядок действий для дежурного и поддержки (DEVELOPMENT_PLAN 8.4, ARCHITECTURE §13). Runbook
считается проверенным после прогона «на сухую»: дата и кто прогонял — в таблице.

| Runbook | Когда | Прогон «на сухую» |
|---|---|---|
| [stage-bootstrap.md](stage-bootstrap.md) | Подъём stage с нуля: Hetzner, Cloudflare, Kamal, Workers, бот (0.25a–e) | при первом подъёме stage |
| [prod-bootstrap.md](prod-bootstrap.md) | Подъём prod с нуля: app-1 и db-1, PostgreSQL, Cloudflare, ручной релиз, Access (3.1a–c) | при первом подъёме prod |
| [restore.md](restore.md) | Потеря или порча данных БД, проверка бэкапов | после 3.2 (restore-test) |
| [release-rollback.md](release-rollback.md) | Релиз сломал прод | после прод-контура 3.1 |
| [secrets-rotation.md](secrets-rotation.md) | Плановая ротация, утечка ключа, K43 перед запуском | при K43 |
| [data-breach.md](data-breach.md) | Утечка или подозрение на утечку персональных данных | учебный прогон до 8.5 |
| [data-export.md](data-export.md) | Запрос пользователя на копию данных (ZZPL ст. 26) | 2.12b |
| [deletion-request.md](deletion-request.md) | Запрос на удаление аккаунта (ZZPL ст. 30) | 2.12b |

Общие правила:
- Значения секретов не печатаются в терминал и не пересылаются в чат — правила обращения с
  секретами в [OWNER_CHECKLIST](../../docs/OWNER_CHECKLIST.md) («Правила обращения с секретами»).
- Каждое действие персонала с персональными данными пишется в `platform.audit_log` с номером
  обращения или инцидента.
- После инцидента — короткий разбор в `docs/incidents/<дата>-<кратко>.md`: хронология, причина,
  что изменили.
