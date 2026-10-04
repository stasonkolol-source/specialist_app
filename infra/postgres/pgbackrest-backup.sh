#!/usr/bin/env bash
# Плановый бэкап pgBackRest на db-1 (DEVELOPMENT_PLAN 3.2, ADR-0015): по воскресеньям полный, в
# остальные дни дифференциальный. Ставит infra/postgres/provision.sh в /usr/local/sbin, запускает
# sosed-pgbackrest-backup.timer от имени postgres. Без --repo pgBackRest пишет бэкап только в repo1,
# поэтому репозитории — по очереди: сбой одного провайдера не мешает копии у другого, но запуск
# считается неудачным. WAL идёт в оба репозитория сам (archive_command, archive-async).
#
# Healthchecks (K33): /start перед бэкапом, затем пустой пинг или /fail с хвостом вывода pgBackRest
# (пароли и ключи он сам заменяет на <redacted>). Адрес — HEALTHCHECK_URL из EnvironmentFile юнита
# (0600 root): имя без префикса PGBACKREST_ — такие переменные pgBackRest читает как свои опции и
# ругается на незнакомую.
set -euo pipefail

STANZA=specialist
CONF=/etc/pgbackrest/pgbackrest.conf

type=${1:-auto}
if [[ "$type" == auto ]]; then
  # без полного бэкапа в репозитории pgBackRest сам повышает diff до полного
  type='diff'
  [[ "$(date -u +%u)" == 7 ]] && type='full'
fi
[[ "$type" == full || "$type" == diff ]] || {
  echo "usage: $0 [auto|full|diff]" >&2
  exit 2
}

log=$(mktemp)
trap 'rm -f "$log" "$log.tail"' EXIT

ping() { # ping <суффикс> [тело] — недоступный Healthchecks бэкап не роняет
  [[ -n "${HEALTHCHECK_URL:-}" ]] || return 0
  local body=()
  [[ -z "${2:-}" ]] || body=(--data-binary "@$2")
  curl -fsS -m 10 --retry 3 -o /dev/null "${body[@]}" "$HEALTHCHECK_URL$1" || true
}

repos=$(sed -n 's/^repo\([0-9][0-9]*\)-type=.*/\1/p' "$CONF")
[[ -n "$repos" ]] || {
  echo "pgbackrest-backup: в $CONF нет репозиториев" >&2
  exit 1
}

ping /start
status=0
for repo in $repos; do
  echo "pgbackrest-backup: $type → repo$repo" | tee -a "$log"
  if ! pgbackrest --stanza="$STANZA" --repo="$repo" --type="$type" backup 2>&1 | tee -a "$log"; then
    status=1
    echo "pgbackrest-backup: repo$repo — ошибка" | tee -a "$log"
  fi
done

tail -c 10000 "$log" > "$log.tail"
if [[ "$status" == 0 ]]; then
  ping "" "$log.tail"
else
  ping /fail "$log.tail"
fi
exit "$status"
