# PostgreSQL 18 + PostGIS для dev, CI (testcontainers), stage и prod (ADR-0005).
#
# Официальный образ postgres (Debian trixie) уже содержит репозиторий PGDG и $PG_MAJOR,
# поэтому PostGIS ставится нативным пакетом под текущую архитектуру (arm64 и amd64).
# Образ postgis/postgis остаётся только amd64 — на Apple Silicon не используем.
# Проверено в лаборатории 2026-09-26: PostgreSQL 18.6, PostGIS 3.6.4 (research/07).
#
# Сборка: make pg-image
ARG PG_IMAGE=postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722
FROM ${PG_IMAGE}

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "postgresql-${PG_MAJOR}-postgis-3" \
        "postgresql-${PG_MAJOR}-postgis-3-scripts"; \
    rm -rf /var/lib/apt/lists/*; \
    dpkg-query -W -f='${Package} ${Version}\n' "postgresql-${PG_MAJOR}*" > /usr/local/share/pg-packages.txt

# Один bootstrap для dev, stage и prod: роли, их параметры, расширения, права по умолчанию.
COPY bootstrap.sql /opt/specialist/bootstrap.sql
COPY initdb/ /docker-entrypoint-initdb.d/

# Кластер создаётся с builtin-провайдером и C.UTF-8 (ADR-0005): верные upper/lower и ctype
# для кириллицы и сербской латиницы, без зависимости от версии glibc.
ENV POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale-provider=builtin --builtin-locale=C.UTF-8"

LABEL org.opencontainers.image.title="specialist-postgres" \
      org.opencontainers.image.description="PostgreSQL 18 + PostGIS 3.6 с bootstrap ролей"
