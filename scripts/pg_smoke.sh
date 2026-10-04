#!/usr/bin/env bash
# make pg-smoke: локаль, pg_trgm, PostGIS и параметры ролей (DEVELOPMENT_PLAN 0.3).
# Stage (0.25c): make pg-smoke ENV=stage и pre-deploy Kamal отдают этот же скрипт bash на сервере
# (ssh … 'PG_SMOKE_CONTAINER=sosed-postgres bash -s' < scripts/pg_smoke.sh) — БД там accessory Kamal.
# Prod (3.1b): так же на db-1 через app-1 с PG_SMOKE_LOCAL=1 — PostgreSQL из пакетов, вход peer.
set -euo pipefail

if [[ -n "${PG_SMOKE_CONTAINER:-}" ]]; then
  # без -i: stdin занят самим скриптом (bash -s)
  RUN=(docker exec "$PG_SMOKE_CONTAINER")
elif [[ -n "${PG_SMOKE_LOCAL:-}" ]]; then
  # root на db-1: суперпользователь только через локальный сокет (pg_hba: local postgres peer)
  RUN=(runuser -u postgres --)
else
  RUN=(docker compose -p specialist-dev -f infra/compose/docker-compose.dev.yml --env-file infra/compose/.env exec -T postgres)
fi

q() { "${RUN[@]}" psql -U postgres -d specialist -v ON_ERROR_STOP=1 -Atc "$1"; }
fail() { echo "pg-smoke: FAIL — $1" >&2; exit 1; }

# PostgreSQL 18: lc_ctype больше не GUC — смотрим провайдер и локаль базы в каталоге.
locale=$(q "SELECT datlocprovider::text || '|' || coalesce(datlocale, '') || '|' || datctype FROM pg_database WHERE datname = 'specialist'")
IFS='|' read -r provider builtin_locale ctype <<< "$locale"
[[ "$provider" == "b" && "$builtin_locale" == "C.UTF-8" ]] || fail "locale provider=$provider locale=$builtin_locale, expected builtin C.UTF-8"
[[ "$ctype" == *[Uu][Tt][Ff]*8* ]] || fail "datctype=$ctype is not UTF-8 (pg_trgm breaks on Cyrillic, research/07)"
echo "locale              builtin $builtin_locale (ctype $ctype)"

trgm=$(q "SELECT show_trgm('тест')::text")
[[ -n "$trgm" && "$trgm" != "{}" ]] || fail "show_trgm('тест') is empty — wrong ctype?"
echo "show_trgm('тест')   $trgm"

postgis=$(q "SELECT postgis_lib_version()")
[[ -n "$postgis" ]] || fail "PostGIS is not available"
echo "postgis             $postgis"

upper=$(q "SELECT upper('ђорђе šđčćž')")
[[ "$upper" == "ЂОРЂЕ ŠĐČĆŽ" ]] || fail "upper() is not Unicode-aware: $upper"
echo "upper()             $upper"

app_cfg=$(q "SELECT array_to_string(rolconfig, ',') FROM pg_roles WHERE rolname = 'app'")
for setting in max_parallel_workers_per_gather=0 plan_cache_mode=force_custom_plan statement_timeout=5s idle_in_transaction_session_timeout=30s; do
  [[ "$app_cfg" == *"$setting"* ]] || fail "role app lacks $setting"
done
echo "role app            $app_cfg"

mig_cfg=$(q "SELECT array_to_string(rolconfig, ',') FROM pg_roles WHERE rolname = 'migrator'")
[[ "$mig_cfg" == *"lock_timeout=3s"* ]] || fail "role migrator lacks lock_timeout=3s"
echo "role migrator       $mig_cfg"

owner=$(q "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'specialist'")
[[ "$owner" == "migrator" ]] || fail "database owner is $owner, expected migrator"
echo "database owner      $owner"

for ext in postgis pg_trgm unaccent btree_gin btree_gist pg_stat_statements; do
  [[ "$(q "SELECT count(*) FROM pg_extension WHERE extname = '$ext'")" == "1" ]] || fail "extension $ext missing"
done
echo "extensions          postgis pg_trgm unaccent btree_gin btree_gist pg_stat_statements"
echo "pg-smoke: OK"
