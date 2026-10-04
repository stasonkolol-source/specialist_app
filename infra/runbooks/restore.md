# Восстановление базы данных

Бэкапы — pgBackRest на `db-1`: полный раз в неделю, дифференциальный ежедневно, WAL непрерывно;
два репозитория (Hetzner Object Storage — `repo1`, Backblaze B2 — `repo2`), шифрование
aes-256-cbc, PITR 14 дней (ARCHITECTURE §13.5, ADR-0015, DEVELOPMENT_PLAN 3.2). Цели: RPO ≤ 5 мин,
RTO ≤ 2 ч (§2.4).

> Черновик 8.4. Шаг 3.2 дописывает имя stanza, место копий паролей шифрования (K10a) и
> измеренные RPO/RTO; до этого команды — по образцу, с `<stanza>`.

## 0. Решить, что восстанавливаем

| Ситуация | Что делать |
|---|---|
| Сломана вся БД или диск `db-1` | Полное восстановление на месте или на новую VM (§2) |
| Испорчены данные (ошибочная миграция, удаление) с известного момента | PITR на момент **до** ошибки (§2) |
| Нужно вернуть несколько строк | Восстановить на временную VM (§3) и перенести строки вручную |

Время ошибки берём из логов (Grafana Loki: `http_request`, `alembic`) и `platform.audit_log`.

## 1. Остановить запись

1. Включить техработы: админка → client-config → флаг `platform.maintenance` (Mini App покажет S49,
   API ответит 503 `maintenance`).
2. Остановить процессы, которые пишут в БД:
   ```bash
   kamal app stop -d production --roles web,worker,worker-media,bot
   ```
3. Записать в канал инцидента: время начала, кто ведёт, выбранная точка восстановления.

## 2. Полное восстановление или PITR на `db-1`

```bash
ssh db-1
sudo -u postgres pgbackrest --stanza=<stanza> info          # какие бэкапы есть, в обоих repo
sudo systemctl stop postgresql
# PITR: --type=time на момент до ошибки, UTC; полное — без --type/--target
sudo -u postgres pgbackrest --stanza=<stanza> --delta \
  --type=time --target="2027-03-01 10:15:00+00" --target-action=promote restore
sudo systemctl start postgresql
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"      # f — восстановление закончено
```

- `repo1` недоступен — добавить `--repo=2` (B2).
- Пароли шифрования репозиториев на сервере есть; если сервер потерян — взять копию из менеджера
  паролей (K10a), а не из чата.
- Новая VM вместо `db-1`: Terraform `infra/terraform/production`, затем установка pgBackRest с тем же
  конфигом и `restore` без `--delta`.

## 3. Восстановление на временную VM (частичный возврат данных)

Тот же порядок, что делает `restore-test.yml` (3.2): временная VM в проекте `specialist-backup`,
`pgbackrest restore --type=time …`, затем нужные строки — `COPY (SELECT …) TO STDOUT` и
`COPY … FROM STDIN` в прод под ролью `migrator`. Перенос строк с ПД пишется в `platform.audit_log`
с номером инцидента. VM удалить сразу после переноса.

## 4. Проверить и вернуть трафик

1. Smoke: `SELECT postgis_full_version();`, `SELECT show_trgm('тест');`, число строк ключевых
   таблиц (`identity.users`, `jobs.jobs`, `messaging.messages`) против ожиданий.
2. Миграции: `kamal app exec -d production 'alembic current'` — голова совпадает с релизом. Если
   PITR вернул схему до миграции — либо `alembic upgrade head`, либо откат релиза
   ([release-rollback.md](release-rollback.md)).
3. Поднять процессы: `kamal app boot -d production`; `/up` отвечает; выключить `platform.maintenance`.
4. Read-model поиска догоняет сама; если нет — `cli reindex`.
5. Записать: точку восстановления, фактические RPO (что потеряно) и RTO, ссылку на разбор.

Потерялись данные пользователей или к ним мог быть доступ — дальше
[data-breach.md](data-breach.md).
