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
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


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

# Entrypoint: фиксит права на volume-директории, затем переключается на appuser
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 8000

# CMD определён в docker-compose для гибкости запуска
# (backend, celery worker, celery beat — один образ, разные команды)
