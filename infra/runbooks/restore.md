# Восстановление базы данных

Бэкапы — pgBackRest на `db-1`, стенза `specialist`: полный раз в неделю (воскресенье), дифференциальный
в остальные дни, WAL непрерывно (archive-async, сегмент закрывается не реже раза в минуту). Два
репозитория, оба с шифрованием aes-256-cbc и своим паролем: `repo1` — Hetzner Object Storage в проекте
`specialist-backup` (K36), `repo2` — Backblaze B2, регион EU (K37); путь в бакете — `/prod`. Хранение —
4 полных бэкапа, PITR не меньше 14 дней (ARCHITECTURE §13.5, ADR-0015, DEVELOPMENT_PLAN 3.2). Цели:
RPO ≤ 5 мин, RTO ≤ 2 ч (§2.4). Как включить — [prod-bootstrap.md](prod-bootstrap.md), раздел «Бэкапы».
Stage не бэкапится: там тестовые данные (план 3.2 — только prod).

## Где что лежит

| Что | Где |
|---|---|
| Конфиг pgBackRest | `/etc/pgbackrest/pgbackrest.conf` на `db-1` (0640 root:postgres), рендерит `infra/postgres/provision.sh` из `pgbackrest.conf.tmpl` |
| Расписание | `sosed-pgbackrest-backup.timer` — ежедневно 01:30 UTC плюс до 30 мин; сервис запускает `/usr/local/sbin/sosed-pgbackrest-backup` (`infra/postgres/pgbackrest-backup.sh`) от `postgres` |
| Журнал бэкапов | `journalctl -u sosed-pgbackrest-backup`, `/var/log/pgbackrest/` |
| Пинги | Healthchecks (K33): «pgBackRest» — каждый запуск таймера, «restore-test» — каждый restore-тест |
| Пароль шифрования `repo1` | секрет `PGBACKREST_REPO1_CIPHER_PASS` (сервер) и `RESTORE_TEST_REPO1_CIPHER_PASS` (restore-тест); **копия в менеджере паролей: `<заполняет владелец: хранилище specialist-prod, имя записи>`** |
| Пароль шифрования `repo2` | `PGBACKREST_REPO2_CIPHER_PASS` и `RESTORE_TEST_REPO2_CIPHER_PASS`; **копия: `<заполняет владелец>`** |
| S3-ключи репозиториев | секреты `PGBACKREST_REPO{1,2}_S3_KEY{,_SECRET}`, копии — там же (K10a) |

Без пароля шифрования бэкап не расшифровать ничем: при потере сервера и GitHub он есть только в
менеджере паролей (K10a).

## 0. Решить, что восстанавливаем

| Ситуация | Что делать |
|---|---|
| Сломана вся БД или диск `db-1` | Полное восстановление на месте (§2) или на новую VM (§2а) |
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

Вход на `db-1` — только через `app-1`: `ssh -J root@<PROD_HOST> root@10.20.1.20`.

```bash
systemctl stop sosed-pgbackrest-backup.timer                # бэкап посреди restore не нужен
sudo -u postgres pgbackrest --stanza=specialist info        # какие бэкапы есть, в обоих repo
systemctl stop postgresql@18-main
# PITR: --type=time на момент до ошибки, UTC; полное — без --type/--target (весь архив WAL)
sudo -u postgres pgbackrest --stanza=specialist --delta \
  --type=time --target="2027-03-01 10:15:00+00" --target-action=promote restore
systemctl start postgresql@18-main
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"      # f — восстановление закончено
systemctl start sosed-pgbackrest-backup.timer
sudo -u postgres /usr/local/sbin/sosed-pgbackrest-backup full   # новая линия времени — сразу полный бэкап
```

- `repo1` недоступен — добавить `--repo=2` (B2).
- `--archive-mode=off` здесь **не** ставить: это сервер prod, архив WAL ему нужен.
- Пароли шифрования на сервере есть; если их там нет — копия из менеджера паролей (K10a), не из чата.

### 2а. Новая VM вместо `db-1`

1. Новая `db-1` — `infra/terraform/prod` (у `db-1` стоит `prevent_destroy`: снять — отдельной правкой
   по решению владельца) и [prod-bootstrap.md](prod-bootstrap.md) §1, проверка cloud-init.
2. `make db-provision ENV=prod` (или job `db-provision`) с ключами pgBackRest. На новой VM он создаст
   пустой кластер, отрендерит конфиги и **упадёт на `stanza-create`**: в репозитории стенза старого
   кластера. Так и должно быть — конфиг pgBackRest уже на месте.
3. На `db-1`:
   ```bash
   systemctl stop postgresql@18-main
   find /var/lib/postgresql/18/main -mindepth 1 -delete
   sudo -u postgres pgbackrest --stanza=specialist restore    # PITR — с --type=time … как в §2
   systemctl start postgresql@18-main                        # ждать pg_is_in_recovery() = f
   ```
4. `make db-provision ENV=prod` ещё раз: теперь стенза совпадает, `check` зелёный, таймер включён.
5. Сразу полный бэкап (последняя команда §2).

## 3. Восстановление на временную VM (частичный возврат данных)

Тот же порядок, что делает `restore-test.yml`: временная VM в проекте `specialist-backup`
(`infra/postgres/restore-vm.sh create`), на ней `infra/postgres/restore-check.sh` — пакеты, конфиг
одного репозитория, `pgbackrest restore --type=time …` с `--archive-mode=off` (копия не пишет WAL в архив
prod). Затем нужные строки — `COPY (SELECT …) TO STDOUT` и `COPY … FROM STDIN` в прод под ролью
`migrator`. Перенос строк с ПД пишется в `platform.audit_log` с номером инцидента. VM удалить сразу после
переноса (`restore-vm.sh delete <run>`). Ручной VM не ставить метку `purpose=restore-test`: restore-тест
удаляет такие VM старше 3 часов.

## 4. Проверить и вернуть трафик

1. Smoke: `make pg-smoke ENV=prod`; `SELECT postgis_full_version();`, число строк ключевых таблиц
   (`identity.users`, `jobs.jobs`, `messaging.messages`) против ожиданий.
2. Миграции: `kamal app exec -d production 'alembic current'` — голова совпадает с релизом. Если
   PITR вернул схему до миграции — либо `alembic upgrade head`, либо откат релиза
   ([release-rollback.md](release-rollback.md)).
3. Поднять процессы: `kamal app boot -d production`; `/up` отвечает; выключить `platform.maintenance`.
4. Read-model поиска догоняет сама; если нет — `cli reindex`.
5. Записать: точку восстановления, фактические RPO (что потеряно) и RTO, ссылку на разбор.

Потерялись данные пользователей или к ним мог быть доступ — дальше
[data-breach.md](data-breach.md).

## Restore-тест (ежемесячно)

`.github/workflows/restore-test.yml` — 3-го числа в 05:23 UTC и вручную (Actions → restore-test → Run
workflow; `gh workflow run restore-test.yml`). Job в environment `production`: запуск ждёт
подтверждения required reviewers, как релиз. Шаги:

1. Выбор репозитория: `repo1` в нечётные месяцы, `repo2` в чётные (вручную — параметр `repo`).
2. RPO-маркер на `db-1` — `make rpo-mark ENV=prod` (`infra/postgres/rpo-mark.sh`): строка в отдельной базе
   `backup_check` (база приложения не трогается), момент T сразу после её коммита, через 2 секунды —
   вторая строка; ожидание, пока сегмент WAL с ними уйдёт в архив, и **отставание архива** — от T до
   архивации, норма ≤ 300 с. Заодно версии пакетов `db-1`. Без `PROD_HOST`/`PROD_DB_IP` или с
   `rpo = false` шаг пропускается и восстанавливается весь архив.
3. Временная VM (CX33, Ubuntu 24.04, `nbg1`) в проекте `specialist-backup`, метки `purpose=restore-test`
   и `run=<id запуска>`.
4. На VM — `infra/postgres/restore-check.sh`: PGDG-пакеты тех же версий, что на `db-1`; конфиг только
   проверяемого репозитория с паролем шифрования **из секрета `RESTORE_TEST_REPO<n>_CIPHER_PASS`** —
   это копия из менеджера паролей, не значение с сервера (K10a); `pgbackrest restore` — PITR на T;
   ожидание promote; `scripts/pg_smoke.sh`, `postgis_full_version()`, ревизия миграций, число строк;
   маркер: «до T» есть, «после T» нет — восстановление остановилось ровно на T.
5. Вердикт в Summary запуска: RTO — от создания VM до зелёного smoke (норма ≤ 120 мин) и RPO.
   Репозиторий публичный: бэкап, число строк, размер базы и версии — только в теле пинга Healthchecks
   (успех или `/fail` со ссылкой на запуск), Healthchecks → проверка «restore-test» → Events.
6. VM и ключ удаляются всегда (`if: always()`), плюс подметание забытых VM restore-теста старше 3 часов.

Красный restore-тест: ссылка на запуск — в письме Healthchecks. Частые причины: неверная копия пароля
шифрования (`pgbackrest info` падает — сверить менеджер паролей с сервером, **не** меняя
`PGBACKREST_REPO*_CIPHER_PASS`), отставание архива WAL (`pg_stat_archiver` на `db-1`, журнал
`/var/log/pgbackrest/`), нет места или лимита серверов в проекте `specialist-backup`.

## RPO и RTO

| Показатель | Цель | Как меряется | Измерено |
|---|---|---|---|
| RPO — отставание архива WAL | ≤ 5 мин | `rpo-mark.sh`: от коммита маркера до архивации его сегмента | измерить на первом прогоне |
| RPO — PITR на момент T | маркер «до» есть, «после» нет | `restore-check.sh` на временной VM | измерить на первом прогоне |
| RTO — новая VM → рабочая БД | ≤ 2 ч | `restore-test.yml`: от создания VM до зелёного smoke | измерить на первом прогоне |
| Время restore | — | Summary: «restore и WAL»; размер базы — в пинге Healthchecks, сюда не вписывать (репозиторий публичный) | измерить на первом прогоне |

После первого зелёного прогона (критерий 3.2) — вписать числа и дату; дальше — обновлять, если RTO
вырос больше чем на треть.
