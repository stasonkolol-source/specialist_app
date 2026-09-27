#!/bin/sh
# Роль процесса в едином образе backend (DEVELOPMENT_PLAN 0.23).
set -eu
role="${1:-web}"
[ "$#" -gt 0 ] && shift
case "$role" in
  web) exec python -m app.entrypoints.web ;;
  bot) exec python -m app.entrypoints.bot ;;
  worker) exec python -m app.entrypoints.worker --role worker ;;
  worker-media) exec python -m app.entrypoints.worker --role worker-media ;;
  migrate) exec alembic upgrade head ;;
  cli) exec python -m app.entrypoints.cli "$@" ;;
  *)
    echo "unknown role: $role (web | bot | worker | worker-media | migrate | cli)" >&2
    exit 64
    ;;
esac
