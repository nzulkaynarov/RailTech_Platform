# syntax=docker/dockerfile:1.7
# Один образ EDS для api, worker и миграций: процесс выбирается командой (`python -m app api|worker`,
# `alembic upgrade head`). Образец — apps/crm/backend/Dockerfile и apps/platform/bff/Dockerfile (тот же базовый образ
# Debian и uv, чтобы cpu-baseline-check и прод проверяли одну линию образов; Wolfi/Alpine не используются, S0-7).
#
# Шина событий (ADR-0014, решение L14): пакеты `packages/rt-bus` и `packages/contracts` лежат вне контекста сборки
# (`apps/eds`) и приходят именованными контекстами `rtbus` и `contracts`:
#   docker build --build-context rtbus=packages/rt-bus --build-context contracts=packages/contracts …
# (в compose — `additional_contexts`, в Actions — `build-contexts`). Пути path-зависимостей в pyproject.toml/uv.lock
# относительные (`../../packages/…`), поэтому `uv sync` идёт в дереве как в репозитории (/repo/apps/eds); код — в /app.

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    RT_BUS_CONTRACTS_DIR=/opt/rt/contracts/events \
    RT_BUS_SUBSCRIPTIONS=/opt/rt/contracts/bus/subscriptions.yaml
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

FROM base AS deps
COPY --from=rtbus . /repo/packages/rt-bus
COPY --from=contracts generated/python /repo/packages/contracts/generated/python
COPY --from=contracts events /opt/rt/contracts/events
COPY --from=contracts bus /opt/rt/contracts/bus
WORKDIR /repo/apps/eds
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
WORKDIR /app
COPY pyproject.toml uv.lock ./

# dev: + dev-зависимости, код монтируется volume'ом (infra/compose/dev.yml)
FROM deps AS dev
WORKDIR /repo/apps/eds
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
WORKDIR /app
USER app
EXPOSE 8000
CMD ["python", "-m", "app", "api", "--reload"]

FROM deps AS prod
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"]
CMD ["python", "-m", "app", "api"]
