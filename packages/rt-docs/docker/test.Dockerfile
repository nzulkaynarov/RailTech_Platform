# Образ тестов rt-docs: тот же базовый образ и uv, что у сервисов (apps/eds/Dockerfile — python:3.12-slim-trixie, uv 0.13.0),
# плюс системные библиотеки WeasyPrint (pango, pangoft2, harfbuzz-subset). Один образ на всех машинах (make check-rt-docs) —
# одна версия pango/harfbuzz/freetype, поэтому число страниц эталонов совпадает. Шрифты документа — только вшитые в пакет
# (rt_docs/fonts): системные (DejaVu приходит зависимостью fontconfig) рендер не видит — docs/architecture/rt-docs.md §4.
# Не образ прода: в стенд и деплой не входит; имя файла без префикса «Dockerfile», чтобы правка не запускала сборку
# 11 образов прода под qemu64 (фильтр `cpu` в ci.yml), если пакет подключат к CI. Код и контракт монтируются только для чтения (scripts/in_container.sh).

FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

# Базовый образ закреплён digest'ом (индекс multi-arch, 2026-10-28): смена pango/harfbuzz — только осознанной правкой этой строки,
# после неё — полный прогон эталонов и ручная проверка под qemu64 (docs/architecture/rt-docs.md §6).
FROM python:3.12-slim-trixie@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f
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
