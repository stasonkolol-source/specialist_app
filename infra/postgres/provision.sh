#!/usr/bin/env bash
# PostgreSQL на db-1 (DEVELOPMENT_PLAN 3.1b, ADR-0015): кластер с builtin C.UTF-8, тот же
# bootstrap.sql, что в dev-образе и на stage (роли с параметрами, расширения), pg_hba только из
# приватной сети с TLS, настройки под память VM; pgBackRest — когда пришли ключи репозиториев (3.2):
# конфиг, стенза, архив WAL и таймер бэкапов sosed-pgbackrest-backup.timer.
#
# Запускает make db-provision ENV=prod (или job db-provision в deploy-production): файлы каталога
# infra/postgres лежат рядом в /opt/sosed/postgres, значения приходят строками ИМЯ=значение на stdin —
# не в argv (их видно в ps) и не в файлах. Идемпотентен: повторный запуск ничего не меняет и БД не
# перезапускает; перезапуск — только если изменился параметр, которому он нужен (pending_restart).
set -euo pipefail
shopt -u patsub_replacement 2>/dev/null || true # «&» в ключах S3 — литерал, а не найденный текст

PG_MAJOR=18
CLUSTER=main
DB=specialist
STANZA=specialist
HERE=$(cd "$(dirname "$0")" && pwd)
CONF_DIR=/etc/postgresql/$PG_MAJOR/$CLUSTER

log() { echo "db-provision: $*"; }
fail() {
  echo "db-provision: FAIL — $*" >&2
  exit 1
}

# --- значения со stdin ---
ROLE_VARS="APP_DB_PASSWORD MIGRATOR_DB_PASSWORD READONLY_DB_PASSWORD BACKUP_DB_PASSWORD"
REPO_VARS="PGBACKREST_REPO1_S3_ENDPOINT PGBACKREST_REPO1_S3_REGION PGBACKREST_REPO1_S3_BUCKET PGBACKREST_REPO1_S3_KEY PGBACKREST_REPO1_S3_KEY_SECRET PGBACKREST_REPO1_CIPHER_PASS"
REPO_VARS+=" PGBACKREST_REPO2_S3_ENDPOINT PGBACKREST_REPO2_S3_REGION PGBACKREST_REPO2_S3_BUCKET PGBACKREST_REPO2_S3_KEY PGBACKREST_REPO2_S3_KEY_SECRET PGBACKREST_REPO2_CIPHER_PASS"
ALLOWED=" $ROLE_VARS $REPO_VARS MONITORING_DB_PASSWORD PGBACKREST_HEALTHCHECK_URL DB_LISTEN_IP DB_SUBNET "
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  key=${line%%=*}
  [[ "$ALLOWED" == *" $key "* ]] || fail "неизвестное имя $key"
  printf -v "$key" '%s' "${line#*=}"
done

for name in $ROLE_VARS; do
  # пароли входят в DSN приложения: только [A-Za-z0-9_-] (make gen-secret, openssl rand -hex)
  [[ "${!name:-}" =~ ^[A-Za-z0-9_-]{24,}$ ]] || fail "$name: пусто или не [A-Za-z0-9_-]{24,}"
done
# роль monitoring (postgres_exporter в Alloy на app-1, 3.3) — по желанию: без пароля войти ею нельзя
[[ -z "${MONITORING_DB_PASSWORD:-}" || "$MONITORING_DB_PASSWORD" =~ ^[A-Za-z0-9_-]{24,}$ ]] ||
  fail "MONITORING_DB_PASSWORD: не [A-Za-z0-9_-]{24,}"
[[ "${DB_LISTEN_IP:-}" =~ ^[0-9.]+$ ]] || fail "DB_LISTEN_IP — адрес db-1 в приватной сети"
[[ "${DB_SUBNET:-}" =~ ^[0-9.]+/[0-9]+$ ]] || fail "DB_SUBNET — подсеть prod (CIDR)"
[[ -z "${PGBACKREST_HEALTHCHECK_URL:-}" || "$PGBACKREST_HEALTHCHECK_URL" =~ ^https://[A-Za-z0-9./_-]+$ ]] ||
  fail "PGBACKREST_HEALTHCHECK_URL — ping URL Healthchecks вида https://hc-ping.com/<uuid> (K33)"
# Бэкапы уже включены, а ключей нет (забыли передать): без этой проверки archive_command вернулся бы в
# /bin/true и молча порвал цепочку PITR. Выключают бэкапы только вручную, по runbook.
if [[ -z "${PGBACKREST_REPO1_S3_KEY:-}" ]] && grep -qs '^repo1-type=' /etc/pgbackrest/pgbackrest.conf; then
  fail "на db-1 бэкапы pgBackRest включены, а ключей PGBACKREST_REPO1_* в stdin нет — передайте их (prod-bootstrap.md, «Бэкапы»)"
fi

command -v pg_createcluster >/dev/null && [[ -x /usr/lib/postgresql/$PG_MAJOR/bin/postgres ]] ||
  fail "нет пакетов PostgreSQL $PG_MAJOR: cloud-init ещё не закончил? (cloud-init status --wait)"

psql_su() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -q "$@"; }

# --- кластер: builtin C.UTF-8, как POSTGRES_INITDB_ARGS dev-образа (ADR-0005) ---
if ! pg_lsclusters -h | awk '{print $1 "/" $2}' | grep -qx "$PG_MAJOR/$CLUSTER"; then
  log "initdb $PG_MAJOR/$CLUSTER: UTF8, builtin C.UTF-8"
  pg_createcluster --encoding=UTF8 --locale=C.UTF-8 "$PG_MAJOR" "$CLUSTER" -- \
    --locale-provider=builtin --builtin-locale=C.UTF-8
fi

# --- конфигурация: файлы целиком наши, ручные правки перезаписываются ---
changed=0
install_file() { # install_file <путь> <режим> <владелец> — содержимое со stdin, замена только при отличии
  local tmp
  tmp=$(mktemp)
  cat > "$tmp"
  if [[ -f "$1" ]] && cmp -s "$tmp" "$1"; then
    rm -f "$tmp"
    return
  fi
  install -m "$2" -o "${3%:*}" -g "${3#*:}" "$tmp" "$1"
  rm -f "$tmp"
  changed=1
  log "обновлён $1"
}

mem_mb=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
maint_mb=$((mem_mb / 16 > 1024 ? 1024 : mem_mb / 16))

archive_command="/bin/true"
if [[ -n "${PGBACKREST_REPO1_S3_KEY:-}" ]]; then
  archive_command="pgbackrest --stanza=$STANZA archive-push %p"
fi

install_file "$CONF_DIR/conf.d/90-sosed.conf" 0644 postgres:postgres <<EOF
# Управляется infra/postgres/provision.sh (3.1b) — ручные правки перезапишутся.
# Только localhost и приватная сеть: снаружи db-1 PostgreSQL не слушает вовсе.
listen_addresses = 'localhost,$DB_LISTEN_IP'
port = 5432
max_connections = 100
password_encryption = scram-sha-256
# ssl_cert_file — сертификат snakeoil от pg_createcluster: шифрует трафик приватной сети
# (sslmode=require в DSN); подлинность сервера держится на изоляции сети и ufw
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
# память — от размера VM (CX33: 8 GB; при переходе на CX43 пересчитается повторным запуском)
shared_buffers = $((mem_mb / 4))MB
effective_cache_size = $((mem_mb * 3 / 4))MB
maintenance_work_mem = ${maint_mb}MB
work_mem = 16MB
random_page_cost = 1.1
effective_io_concurrency = 200
jit = off
wal_compression = zstd
max_wal_size = 4GB
checkpoint_timeout = 15min
log_min_duration_statement = 500
log_lock_waits = on
log_temp_files = 0
# WAL — в pgBackRest (archive-async, RPO ≤ 5 мин: сегмент закрывается не реже раза в минуту). Пока
# репозиториев нет (до 3.2), WAL не копится на диске: /bin/true; реальных данных до ворот 3.4 нет.
archive_mode = on
archive_timeout = 60
archive_command = '$archive_command'
EOF

install_file "$CONF_DIR/pg_hba.conf" 0640 postgres:postgres <<EOF
# Управляется infra/postgres/provision.sh (3.1b). Суперпользователь — только локально (peer: root на
# db-1 через runuser, pgBackRest); роли приложения — только из приватной сети prod и только по TLS.
# TYPE  DATABASE    USER                          ADDRESS       METHOD
local   all         postgres                                    peer
hostssl $DB  app,migrator,readonly,backup,monitoring  $DB_SUBNET  scram-sha-256
EOF

# --- pgBackRest: конфиг из шаблона, когда в stdin пришли ключи репозиториев (K36, K37; 3.2) ---
if [[ -n "${PGBACKREST_REPO1_S3_KEY:-}" ]]; then
  conf=$(< "$HERE/pgbackrest.conf.tmpl")
  [[ -n "${PGBACKREST_REPO2_S3_KEY:-}" ]] || conf=$(grep -v '^repo2-' <<< "$conf")
  for name in $REPO_VARS; do
    conf=${conf//"@$name@"/"${!name:-}"}
  done
  [[ "$conf" != *@PGBACKREST_REPO*@* ]] || fail "pgbackrest.conf: не все значения переданы ($(grep -o '@PGBACKREST_REPO[A-Z0-9_]*@' <<< "$conf" | sort -u | tr '\n' ' '))"
  install -d -m 0750 -o postgres -g postgres /var/spool/pgbackrest /var/log/pgbackrest
  install_file /etc/pgbackrest/pgbackrest.conf 0640 root:postgres <<< "$conf"
else
  log "ключей pgBackRest нет — WAL не архивируется (archive_command = /bin/true), бэкапы — шаг 3.2"
fi

# --- запуск и применение ---
pg_ctlcluster "$PG_MAJOR" "$CLUSTER" status >/dev/null 2>&1 || pg_ctlcluster "$PG_MAJOR" "$CLUSTER" start
if [[ "$changed" == 1 ]]; then
  pg_ctlcluster "$PG_MAJOR" "$CLUSTER" reload
  sleep 1
  pending=$(psql_su -d postgres -Atc "SELECT string_agg(name, ',') FROM pg_settings WHERE pending_restart")
  if [[ -n "$pending" ]]; then
    log "перезапуск PostgreSQL: $pending"
    pg_ctlcluster "$PG_MAJOR" "$CLUSTER" restart
  fi
fi

# --- node exporter (3.3): метрики хоста db-1 для Alloy на app-1 ---
# Пакет ОС, а не контейнер: Docker на db-1 не ставим. Слушает только адрес приватной сети, ufw пускает
# к порту только подсеть prod; коллекторы — те, ряды которых Alloy оставляет (infra/monitoring/alloy).
if ! dpkg -s prometheus-node-exporter >/dev/null 2>&1; then
  log "установка prometheus-node-exporter"
  apt-get update -q >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends prometheus-node-exporter >/dev/null
fi
pg_changed=$changed # флаг перезапуска PostgreSQL выше уже отработал; здесь он — про node exporter
changed=0
install_file /etc/default/prometheus-node-exporter 0644 root:root <<EOF
# Управляется infra/postgres/provision.sh (3.3) — ручные правки перезапишутся.
ARGS="--web.listen-address=$DB_LISTEN_IP:9100 --collector.disable-defaults --collector.cpu --collector.diskstats --collector.filesystem --collector.loadavg --collector.meminfo --collector.pressure --collector.time"
EOF
[[ "$changed" == 0 ]] || systemctl restart prometheus-node-exporter
changed=$pg_changed
systemctl enable --quiet --now prometheus-node-exporter
ufw allow from "$DB_SUBNET" to any port 9100 proto tcp >/dev/null

# --- база и bootstrap.sql (роли, их параметры, расширения — тот же файл, что в dev и на stage) ---
if [[ "$(psql_su -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$DB'")" != 1 ]]; then
  log "createdb $DB"
  runuser -u postgres -- createdb "$DB"
fi
{
  # пароли — переменными psql со stdin: в argv psql их нет
  printf '\\set dbname %s\n' "$DB"
  printf "\\\\set app_password '%s'\n" "$APP_DB_PASSWORD"
  printf "\\\\set migrator_password '%s'\n" "$MIGRATOR_DB_PASSWORD"
  printf "\\\\set readonly_password '%s'\n" "$READONLY_DB_PASSWORD"
  printf "\\\\set backup_password '%s'\n" "$BACKUP_DB_PASSWORD"
  printf "\\\\set monitoring_password '%s'\n" "${MONITORING_DB_PASSWORD:-}"
  printf '\\i %s\n' "$HERE/bootstrap.sql"
} | psql_su -d postgres
log "bootstrap.sql применён"

if [[ -n "${PGBACKREST_REPO1_S3_KEY:-}" ]]; then
  # stanza-create на существующей стензе с теми же параметрами — no-op
  runuser -u postgres -- pgbackrest --stanza="$STANZA" stanza-create
  runuser -u postgres -- pgbackrest --stanza="$STANZA" check
  log "pgBackRest: стенза $STANZA, архив WAL работает"

  # --- расписание бэкапов (3.2): таймер systemd, полный по воскресеньям, иначе diff ---
  changed=0 # перезапуск PostgreSQL выше уже решён; дальше флаг — про юниты
  install_file /usr/local/sbin/sosed-pgbackrest-backup 0755 root:root < "$HERE/pgbackrest-backup.sh"
  # ping URL — секрет (по нему можно отметить проверку и скрыть сбой, K33): только root, systemd
  # читает файл до смены пользователя; в юнитах и журнале адреса нет
  install -d -m 0750 -o root -g root /etc/sosed
  install_file /etc/sosed/pgbackrest-backup.env 0600 root:root <<< "HEALTHCHECK_URL=${PGBACKREST_HEALTHCHECK_URL:-}"
  install_file /etc/systemd/system/sosed-pgbackrest-backup.service 0644 root:root <<EOF
# Управляется infra/postgres/provision.sh (3.2) — ручные правки перезапишутся.
[Unit]
Description=pgBackRest: бэкап стензы $STANZA (полный по воскресеньям, иначе diff)
After=network-online.target postgresql@$PG_MAJOR-$CLUSTER.service
Wants=network-online.target

[Service]
Type=oneshot
User=postgres
Group=postgres
EnvironmentFile=/etc/sosed/pgbackrest-backup.env
ExecStart=/usr/local/sbin/sosed-pgbackrest-backup auto
# бэкап уступает БД процессор и диск
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
TimeoutStartSec=6h
EOF
  install_file /etc/systemd/system/sosed-pgbackrest-backup.timer 0644 root:root <<EOF
# Управляется infra/postgres/provision.sh (3.2) — ручные правки перезапишутся.
[Unit]
Description=pgBackRest: ежедневный бэкап стензы $STANZA

[Timer]
# ночью по Белграду, до platform.retention_sweep (03:37 UTC); разброс до 30 минут — не в одну
# секунду с чужими ночными заданиями; пропущенный запуск (VM была выключена) — сразу после загрузки
OnCalendar=*-*-* 01:30:00 UTC
RandomizedDelaySec=30min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  [[ "$changed" == 0 ]] || systemctl daemon-reload
  systemctl enable --quiet sosed-pgbackrest-backup.timer
  if [[ "$changed" == 1 ]]; then
    systemctl restart sosed-pgbackrest-backup.timer # новое расписание — сразу, без перезагрузки
  else
    systemctl start sosed-pgbackrest-backup.timer
  fi
  [[ -n "${PGBACKREST_HEALTHCHECK_URL:-}" ]] || log "PGBACKREST_HEALTHCHECK_URL нет — бэкапы идут без пингов Healthchecks"
  # первый бэкап — сразу, а не следующей ночью: до него восстанавливать нечего
  info=$(runuser -u postgres -- pgbackrest --stanza="$STANZA" --output=json info)
  if [[ "$info" == *'"backup":[]'* ]]; then
    systemctl start --no-block sosed-pgbackrest-backup.service
    log "бэкапов ещё нет — первый запущен в фоне: journalctl -u sosed-pgbackrest-backup -f"
  fi
  log "таймер бэкапов: $(systemctl show -P NextElapseUSecRealtime sosed-pgbackrest-backup.timer)"
fi
log "OK ($(runuser -u postgres -- psql -X -Atc 'SHOW server_version' -d postgres), $(pgbackrest version 2>/dev/null || echo 'pgbackrest ?'))"
