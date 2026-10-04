#!/usr/bin/env bash
# Restore-тест, сторона временной VM (DEVELOPMENT_PLAN 3.2): пакеты PGDG тех же версий, что на db-1,
# pgbackrest restore последнего бэкапа со всем архивом WAL или PITR на момент T маркера RPO
# (rpo-mark.sh), затем smoke: scripts/pg_smoke.sh, postgis_full_version(), число строк ключевых
# таблиц, ревизия миграций, маркер.
#
# Запускает .github/workflows/restore-test.yml от root на VM в проекте specialist-backup. Значения —
# строками ИМЯ=значение на stdin, как у provision.sh: не в argv и не в файлах workflow. Stdout — строки
# КЛЮЧ=значение для Summary запуска, ход работы — stderr.
#
# Проверяемый репозиторий на VM всегда repo1: номер — только имя опции в конфиге, в самом репозитории
# его нет. Восстановленный кластер WAL не архивирует (--archive-mode=off и archive_mode = off в
# конфиге): после promote у него новая линия времени, и её история не должна попасть в архив prod.
set -euo pipefail

PG_MAJOR=18
CLUSTER=main
STANZA=specialist
HERE=$(cd "$(dirname "$0")" && pwd)
PGDATA=/var/lib/postgresql/$PG_MAJOR/$CLUSTER
CONF=/etc/pgbackrest/pgbackrest.conf
PACKAGES="postgresql-$PG_MAJOR postgresql-$PG_MAJOR-postgis-3 postgresql-$PG_MAJOR-postgis-3-scripts pgbackrest"

say() { echo "restore-check: $*" >&2; }
fail() {
  echo "restore-check: FAIL — $*" >&2
  exit 1
}
out() { echo "$1=$2"; }
q() { runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -d "$1" -Atc "$2"; }

# --- значения со stdin ---
VARS=" REPO_S3_ENDPOINT REPO_S3_REGION REPO_S3_BUCKET REPO_S3_KEY REPO_S3_KEY_SECRET REPO_CIPHER_PASS REPO_PATH PG_PACKAGES RPO_TARGET RPO_TAG "
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  key=${line%%=*}
  [[ "$VARS" == *" $key "* ]] || fail "неизвестное имя $key"
  printf -v "$key" '%s' "${line#*=}"
done
for name in REPO_S3_ENDPOINT REPO_S3_REGION REPO_S3_BUCKET REPO_S3_KEY REPO_S3_KEY_SECRET REPO_CIPHER_PASS; do
  [[ -n "${!name:-}" ]] || fail "$name пусто — секреты и Variables environment production (prod-bootstrap.md, «Бэкапы»)"
done
[[ -z "${PG_PACKAGES:-}" || "$PG_PACKAGES" =~ ^[a-z0-9.+:~=\ -]+$ ]] || fail "PG_PACKAGES: не список пакет=версия"
[[ -z "${RPO_TARGET:-}" || "$RPO_TARGET" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9:.]+\+00$ ]] || fail "RPO_TARGET: не время UTC"
[[ -z "${RPO_TAG:-}" || "$RPO_TAG" =~ ^rpo-[0-9TZ]+$ ]] || fail "RPO_TAG: не метка rpo-mark.sh"

# --- пакеты: PGDG, как cloud-init db-1 (кластер создаём сами); версии db-1, если они пришли ---
cloud-init status --wait > /dev/null 2>&1 || true
export DEBIAN_FRONTEND=noninteractive
apt=(apt-get -q -y -o DPkg::Lock::Timeout=600) # первая загрузка: unattended-upgrades держит замок
install -d /etc/postgresql-common/createcluster.d /usr/share/postgresql-common/pgdg
echo 'create_main_cluster = false' > /etc/postgresql-common/createcluster.d/00-sosed.conf
curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
# shellcheck source=/dev/null # /etc/os-release есть на VM, не здесь
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" > /etc/apt/sources.list.d/pgdg.list
"${apt[@]}" update > /dev/null
read -ra wanted <<< "${PG_PACKAGES:-$PACKAGES}"
if ! "${apt[@]}" install "${wanted[@]}" > /dev/null; then
  [[ -n "${PG_PACKAGES:-}" ]] || fail "apt-get install $PACKAGES"
  # версии db-1 из PGDG уже убрали: восстанавливаем свежими той же major-версии и отмечаем это
  echo "::warning::версий db-1 ($PG_PACKAGES) в PGDG нет — ставлю текущие"
  read -ra wanted <<< "$PACKAGES"
  "${apt[@]}" install "${wanted[@]}" > /dev/null
fi
read -ra names <<< "$PACKAGES"
# shellcheck disable=SC2016 # ${Package} — формат dpkg-query, не переменная shell
installed=$(dpkg-query -W -f '${Package}=${Version} ' "${names[@]}" | sed 's/ $//')
out vm_packages "$installed"
if [[ -n "${PG_PACKAGES:-}" ]]; then
  out packages_match "$([[ "$installed" == "$PG_PACKAGES" ]] && echo true || echo false)"
fi

# --- pgBackRest: только проверяемый репозиторий ---
install -d -m 0750 -o postgres -g postgres /var/spool/pgbackrest /var/log/pgbackrest
install -d -m 0755 /etc/pgbackrest
install -m 0640 -o root -g postgres /dev/null "$CONF"
cat > "$CONF" <<EOF
[global]
log-level-console=info
log-level-file=off
process-max=4
repo1-type=s3
repo1-s3-endpoint=$REPO_S3_ENDPOINT
repo1-s3-region=$REPO_S3_REGION
repo1-s3-bucket=$REPO_S3_BUCKET
repo1-s3-key=$REPO_S3_KEY
repo1-s3-key-secret=$REPO_S3_KEY_SECRET
repo1-s3-uri-style=path
repo1-path=${REPO_PATH:-/prod}
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=$REPO_CIPHER_PASS

[$STANZA]
pg1-path=$PGDATA
pg1-port=5432
pg1-socket-path=/var/run/postgresql
EOF

# неверный пароль шифрования ломается уже здесь: info расшифровывает backup.info
info=$(runuser -u postgres -- pgbackrest --stanza="$STANZA" --output=json info) ||
  fail "pgbackrest info: репозиторий недоступен или пароль шифрования не тот (копия K10a?)"
python3 - "$info" <<'PY'
import datetime, json, sys

stanza = json.loads(sys.argv[1])[0]
if not stanza["backup"]:
    sys.exit("restore-check: FAIL — в репозитории нет бэкапов")
last = stanza["backup"][-1]
stop = datetime.datetime.fromtimestamp(last["timestamp"]["stop"], datetime.timezone.utc)
print(f"backup_label={last['label']}")
print(f"backup_type={last['type']}")
print(f"backup_stop={stop:%Y-%m-%d %H:%M:%S} UTC")
print(f"backup_made_by=pgBackRest {last['backrest']['version']}")
print(f"backup_db_size_mb={last['info']['size'] // 1048576}")
print(f"backups_in_repo={len(stanza['backup'])}")
PY

# --- кластер: конфиг Debian из pg_createcluster, данные — из бэкапа ---
pg_createcluster --encoding=UTF8 --locale=C.UTF-8 "$PG_MAJOR" "$CLUSTER" -- \
  --locale-provider=builtin --builtin-locale=C.UTF-8 >&2
echo "archive_mode = off" > "/etc/postgresql/$PG_MAJOR/$CLUSTER/conf.d/90-restore-test.conf"
find "$PGDATA" -mindepth 1 -delete

restore=(--stanza="$STANZA" --archive-mode=off)
if [[ -n "${RPO_TARGET:-}" ]]; then
  restore+=(--type=time "--target=$RPO_TARGET" --target-action=promote)
  say "PITR на T = $RPO_TARGET"
else
  say "последний бэкап и весь архив WAL"
fi
t0=$(date +%s)
runuser -u postgres -- pgbackrest "${restore[@]}" restore >&2
# systemd-юнит postgresql@ не ждёт конца восстановления — ждём сами, пока кластер не станет primary
pg_ctlcluster "$PG_MAJOR" "$CLUSTER" start >&2 || true
until [[ "$(q postgres 'SELECT pg_is_in_recovery()' 2> /dev/null)" == f ]]; do
  status=$(pg_lsclusters -h | awk -v v="$PG_MAJOR" -v c="$CLUSTER" '$1 == v && $2 == c {print $4}')
  if [[ "$status" != online* ]]; then
    tail -n 40 "/var/log/postgresql/postgresql-$PG_MAJOR-$CLUSTER.log" >&2 || true
    fail "PostgreSQL остановился во время восстановления"
  fi
  (($(date +%s) - t0 < 7200)) || fail "восстановление дольше 2 ч (RTO)"
  sleep 5
done
out restore_seconds "$(($(date +%s) - t0))"
out last_replayed_xact "$(q postgres 'SELECT pg_last_xact_replay_timestamp()')"
out server_version "$(q postgres 'SHOW server_version')"

# --- smoke: тот же scripts/pg_smoke.sh, что после db-provision, плюс данные ---
PG_SMOKE_LOCAL=1 bash "$HERE/../../scripts/pg_smoke.sh" >&2
out postgis_full_version "$(q specialist 'SELECT postgis_full_version()')"
if [[ "$(q specialist "SELECT to_regclass('platform.alembic_version') IS NOT NULL")" == t ]]; then
  out alembic_revision "$(q specialist 'SELECT string_agg(version_num, ",") FROM platform.alembic_version')"
else
  out alembic_revision "нет — миграций на prod ещё не было"
fi
for table in identity.users specialists.profiles jobs.jobs jobs.responses messaging.messages platform.audit_log; do
  if [[ "$(q specialist "SELECT to_regclass('$table') IS NOT NULL")" == t ]]; then
    out "rows_${table/./_}" "$(q specialist "SELECT count(*) FROM $table")"
  fi
done

if [[ -n "${RPO_TAG:-}" ]]; then
  # PITR на T: маркер «до» на месте, «после» — нет
  got=$(q backup_check "SELECT count(*) FILTER (WHERE tag = '$RPO_TAG-before') || '|' || count(*) FILTER (WHERE tag = '$RPO_TAG-after') FROM markers")
  out rpo_marker_ok "$([[ "$got" == '1|0' ]] && echo true || echo false)"
  out rpo_marker "до T: ${got%|*}, после T: ${got#*|} (ждём 1 и 0)"
fi
say "OK"
