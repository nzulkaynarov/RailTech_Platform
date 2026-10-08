# syntax=docker/dockerfile:1.7
# Один образ для api, worker и MCP-серверов: процесс выбирается командой
# (`python -m app api|worker`, см. app/__main__.py).

FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

FROM python:3.12-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# dev: + dev-зависимости, код монтируется volume'ом (docker-compose.dev.yml)
FROM deps AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
USER app
EXPOSE 8000
CMD ["python", "-m", "app", "api", "--reload"]

FROM deps AS prod
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"]
CMD ["python", "-m", "app", "api"]
