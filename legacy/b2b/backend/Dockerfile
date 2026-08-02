# ==============================================================================
# RailTech Backend — Multi-stage Dockerfile
# Stage 1 (builder): компилирует зависимости с gcc/libpq-dev
# Stage 2 (runtime): минимальный образ, только runtime-библиотеки
# ==============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Системные зависимости для компиляции (только в builder)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# requirements.txt is a fully-pinned, hashed lock (pip-compile from
# requirements.in, INF-05). pip auto-enters --require-hashes mode when any hash
# is present, so a tampered/невоспроизводимый wheel fails the build. psycopg2 is
# built from source here (libpq-dev above) — the binary variant is out (INF-09).
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

# Runtime-зависимости:
#   libpq5          — PostgreSQL клиент
#   libcairo2       — WeasyPrint (PDF рендеринг)
#   libpango-*      — WeasyPrint (типографика)
#   libgdk-pixbuf   — WeasyPrint (изображения в PDF)
#   libffi8         — cffi (WeasyPrint зависимость)
#   shared-mime-info — MIME-типы для openpyxl/pandas
#   curl            — healthcheck в docker-compose
#   fonts-paratype  — PT Sans / PT Serif: печатная кириллица документного класса
#                     (_FONT_STACKS в crm/services/documents.py; DejaVu — только fallback)
#   fonts-inter     — Inter: современный гротеск для sans-стека PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    curl \
    gosu \
    fonts-paratype \
    fonts-inter \
    gettext \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные пакеты из builder
COPY --from=builder /install /usr/local

# Создаём непривилегированного пользователя
RUN useradd -m -u 1000 appuser

# Создаём директории с правильными правами ДО смены пользователя
RUN mkdir -p /app/staticfiles /app/media && \
    chown -R appuser:appuser /app

# Копируем исходники (appuser владеет кодом)
COPY --chown=appuser:appuser . .

# L0 (spec-bilingual-ru-en): компиляция каталогов переводов .po → .mo.
# В git лежат только .po (ревьюируемый исходник), .mo генерируются здесь — иначе бинарник
# в репозитории расходится с исходником. msgfmt напрямую, а не `manage.py compilemessages`:
# команда грузит settings и потребовала бы боевых env-переменных на этапе сборки.
RUN find locale -name '*.po' -exec sh -c 'msgfmt -o "${1%.po}.mo" "$1"' _ {} \;

# Entrypoint: фиксит права на volume-директории, затем переключается на appuser
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 8000

# CMD определён в docker-compose для гибкости запуска
# (backend, celery worker, celery beat — один образ, разные команды)
