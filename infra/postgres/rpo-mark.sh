#!/usr/bin/env bash
# RPO, сторона db-1 (DEVELOPMENT_PLAN 3.2): строка-маркер с моментом T, ожидание, пока WAL с ней уйдёт
# в архив pgBackRest, и отставание архива. Вторая строка пишется через 2 секунды после T: PITR на T
# должен вернуть первую и не вернуть вторую — значит, восстановление остановилось ровно на T, а не на
# конце архива. Без неё PITR и не закончился бы: PostgreSQL 13+ падает, если цель не достигнута, а
# достигнутой она считается по первому коммиту после T.
#
# Маркеры — в отдельной базе backup_check, не в specialist: ни миграции, ни чужой схемы в базе
# приложения. PITR восстанавливает кластер целиком, база едет вместе с остальными.
#
# Запуск — от root на db-1: make rpo-mark ENV=prod (ssh … 'bash -s' < этот файл) или restore-test.yml
# перед восстановлением. Stdout — строки КЛЮЧ=значение для CI ($GITHUB_OUTPUT), пояснения — stderr.
set -euo pipefail

MAX_LAG=300 # RPO ≤ 5 мин (Q27, ADR-0015)
WAIT=900    # дольше — архив WAL не работает, ждать нечего

say() { echo "rpo-mark: $*" >&2; }
fail() {
  echo "rpo-mark: FAIL — $*" >&2
  exit 1
}
# stdin занят самим скриптом (bash -s): psql его не читает
q() { runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -d "$1" -Atc "$2" < /dev/null; }

[[ "$(q postgres "SHOW archive_command")" == pgbackrest* ]] ||
  fail "archive_command — не pgBackRest: бэкапы не включены (prod-bootstrap.md, «Бэкапы»)"

if [[ "$(q postgres "SELECT 1 FROM pg_database WHERE datname = 'backup_check'")" != 1 ]]; then
  runuser -u postgres -- createdb backup_check < /dev/null
  say "создана база backup_check"
fi
q backup_check "CREATE TABLE IF NOT EXISTS markers (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tag text NOT NULL,
  written_at timestamptz NOT NULL DEFAULT clock_timestamp())"

tag="rpo-$(date -u +%Y%m%dT%H%M%SZ)"
q backup_check "INSERT INTO markers (tag) VALUES ('$tag-before')"
# T — после коммита маркера: PITR на T (target-exclusive=n) его включает
target=$(q postgres "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US') || '+00'")
sleep 2
q backup_check "INSERT INTO markers (tag) VALUES ('$tag-after')"
segment=$(q postgres "SELECT pg_walfile_name(pg_current_wal_lsn())")
say "маркер $tag, T = $target, ждём архив WAL $segment (archive_timeout 60 с)"

# имена сегментов одной линии времени сравниваются как строки; .history и .partial сортируются ниже
start=$(date +%s)
until [[ "$(q postgres "SELECT coalesce(last_archived_wal, '') >= '$segment' FROM pg_stat_archiver")" == t ]]; do
  if (($(date +%s) - start > WAIT)); then
    fail "WAL $segment не в архиве за $WAIT с: $(q postgres "SELECT 'ошибок ' || failed_count || ', последняя ' || coalesce(last_failed_wal, '—') || ' в ' || coalesce(last_failed_time::text, '—') FROM pg_stat_archiver")"
  fi
  sleep 5
done
# отставание — от коммита маркера до архива сегмента, в котором уже лежит и коммит после T
lag=$(q postgres "SELECT ceil(extract(epoch FROM last_archived_time - '$target'::timestamptz))::int FROM pg_stat_archiver")
lag_ok=true
((lag <= MAX_LAG)) || lag_ok=false

echo "rpo_tag=$tag"
echo "rpo_target=$target"
echo "rpo_lag_seconds=$lag"
echo "rpo_lag_ok=$lag_ok"
# версии пакетов db-1: restore-test ставит на временную VM те же
# shellcheck disable=SC2016 # ${Package} — формат dpkg-query, не переменная shell
echo "pg_packages=$(dpkg-query -W -f '${Package}=${Version} ' postgresql-18 postgresql-18-postgis-3 postgresql-18-postgis-3-scripts pgbackrest | sed 's/ $//')"

if [[ "$lag_ok" == true ]]; then
  say "OK: отставание архива WAL $lag с (норма ≤ $MAX_LAG с); PITR на T = $target должен вернуть $tag-before без $tag-after"
else
  say "ПРЕВЫШЕНО: отставание архива WAL $lag с > $MAX_LAG с — RPO не выполняется"
fi
