# syntax=docker/dockerfile:1.7
# BFF Платформы: один образ, процесс — uvicorn (app.main:app). Образец — apps/crm/backend/Dockerfile
# (тот же базовый образ и uv, чтобы cpu-baseline-check и прод проверяли одну линию образов).
#
# Шина событий (B5, ADR-0014, решение L14): BFF — подписчик шины. Пакет `packages/rt-bus` и схемы/подписки из
# `packages/contracts` лежат вне контекста сборки (`apps/platform/bff`) и приходят именованными контекстами `rtbus` и
# `contracts`:  docker build --build-context rtbus=packages/rt-bus --build-context contracts=packages/contracts …
# (в compose — `additional_contexts`, в Actions — `build-contexts`). Путь path-зависимости в pyproject.toml/uv.lock
# относительный (`../../../packages/rt-bus`), поэтому `uv sync` идёт в дереве как в репозитории (/repo/apps/platform/bff);
# код приложения — по-прежнему в /app.

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
COPY --from=contracts events /opt/rt/contracts/events
COPY --from=contracts bus /opt/rt/contracts/bus
WORKDIR /repo/apps/platform/bff
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
WORKDIR /app
COPY pyproject.toml uv.lock ./

# dev: + dev-зависимости, код монтируется volume'ом
FROM deps AS dev
WORKDIR /repo/apps/platform/bff
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
WORKDIR /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM deps AS prod
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
