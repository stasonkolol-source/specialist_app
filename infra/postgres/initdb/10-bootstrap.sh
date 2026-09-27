#!/usr/bin/env bash
# Запускается официальным entrypoint образа postgres при первом initdb (только dev и тесты).
# На stage и prod тот же bootstrap.sql применяется командой провижининга.
set -euo pipefail

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${MIGRATOR_DB_PASSWORD:?MIGRATOR_DB_PASSWORD is required}"
: "${READONLY_DB_PASSWORD:?READONLY_DB_PASSWORD is required}"
: "${BACKUP_DB_PASSWORD:?BACKUP_DB_PASSWORD is required}"

psql --username "${POSTGRES_USER}" --dbname postgres \
    -v ON_ERROR_STOP=1 \
    -v dbname="${POSTGRES_DB}" \
    -v app_password="${APP_DB_PASSWORD}" \
    -v migrator_password="${MIGRATOR_DB_PASSWORD}" \
    -v readonly_password="${READONLY_DB_PASSWORD}" \
    -v backup_password="${BACKUP_DB_PASSWORD}" \
    -f /opt/specialist/bootstrap.sql
