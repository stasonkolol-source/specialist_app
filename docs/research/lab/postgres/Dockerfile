# Local-dev PostgreSQL + PostGIS image (multi-arch: arm64 / amd64).
#
# Base: official Docker "postgres" image (Debian trixie). It already ships with the
# PGDG apt repository (apt.postgresql.org) configured and exports $PG_MAJOR, so
# PostGIS and other extensions are installed as native packages for the current
# architecture. The official postgis/postgis image is still amd64-only
# (checked on Docker Hub 2026-09-26), so we do not use it on Apple Silicon.
#
# Tested 2026-09-26 on linux/arm64:
#   postgres:18.6-trixie               -> PostgreSQL 18.6 (PGDG 18.6-1.pgdg13+2)
#   postgresql-18-postgis-3            -> 3.6.4+dfsg-2.pgdg13+1
#   postgresql-18-pgvector (optional)  -> 0.8.6-1.pgdg13+2
#   postgresql-18-cron     (optional)  -> 1.6.8-1.pgdg13+2
#
# Build: docker compose -p specialist-lab build postgres
# Pin the base image by digest for fully reproducible builds, e.g.
#   PG_IMAGE=postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722
ARG PG_IMAGE=postgres:18.6-trixie
FROM ${PG_IMAGE}

# Space-separated PGDG package suffixes installed in addition to PostGIS.
# Leave empty for the minimal dev image: --build-arg EXTRA_EXTENSIONS=""
ARG EXTRA_EXTENSIONS="pgvector cron"

RUN set -eux; \
    apt-get update; \
    pkgs="postgresql-${PG_MAJOR}-postgis-3 postgresql-${PG_MAJOR}-postgis-3-scripts"; \
    for e in ${EXTRA_EXTENSIONS}; do pkgs="$pkgs postgresql-${PG_MAJOR}-$e"; done; \
    apt-get install -y --no-install-recommends $pkgs; \
    rm -rf /var/lib/apt/lists/*; \
    dpkg-query -W -f='${Package} ${Version}\n' "postgresql-${PG_MAJOR}*" > /usr/local/share/pg-packages.txt
