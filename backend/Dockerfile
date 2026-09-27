# syntax=docker/dockerfile:1
# Backend «Сосед» (DEVELOPMENT_PLAN 0.23): один образ, роль — аргумент точки входа:
#   web | bot | worker | worker-media | migrate | cli <команда> (сиды, реиндекс, ключи, OpenAPI).
# Код — в /app/src без установки пакета: пути к locales/, seeds/, migrations/ считаются от него.
# Базовые образы закреплены по digest; обновляет их Dependabot.

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_LOG_JSON=true \
    APP_WEB_HOST=0.0.0.0
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY locales ./locales
COPY seeds ./seeds
COPY src ./src
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/sosed
USER app
EXPOSE 8000
ENTRYPOINT ["sosed"]
CMD ["web"]

LABEL org.opencontainers.image.title="sosed-backend" \
      org.opencontainers.image.description="«Сосед» — backend: web, bot, worker, worker-media, cli"
