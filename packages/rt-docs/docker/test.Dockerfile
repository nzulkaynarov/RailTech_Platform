# Образ тестов rt-docs: тот же базовый образ и uv, что у сервисов (apps/eds/Dockerfile — python:3.12-slim-trixie, uv 0.13.0),
# плюс системные библиотеки WeasyPrint (pango, pangoft2, harfbuzz-subset). Один образ локально и в CI (job rt-docs) — одна
# версия pango/harfbuzz/freetype, поэтому число страниц эталонов совпадает. Шрифты документа — только вшитые в пакет
# (rt_docs/fonts): системные (DejaVu приходит зависимостью fontconfig) рендер не видит — docs/architecture/rt-docs.md §4.
# Не образ прода: в стенд и деплой не входит; имя файла без префикса «Dockerfile», чтобы правка не запускала сборку
# 11 образов прода под qemu64 (фильтр `cpu` в ci.yml). Код и контракт монтируются только для чтения (scripts/in_container.sh).

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12-slim-trixie
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /repo/packages/rt-docs
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project && rm -rf /root/.cache
