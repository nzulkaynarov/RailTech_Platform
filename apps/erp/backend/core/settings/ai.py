"""AI-слой: модель, лимиты импорта, санитарные потолки КП (ARCH-01)."""

import os
from decimal import Decimal

from .infra import *  # noqa: F401,F403 — последовательная композиция настроек

# ── ИИ через общий шлюз LiteLLM (ADR-0005, M1-ERP-06) ───────────────────────
# Код знает только алиасы (intake-model, match-model, draft-model, enrich-model —
# ai/services/gateway.py); какая модель за алиасом и ключи провайдеров — в LiteLLM
# (консоль «Модели ИИ» CRM). ERP получает адрес шлюза и свой ключ как секреты окружения
# (те же имена, что у CRM). Ключ — виртуальный ключ ERP с дневным бюджетом и трейсами
# Langfuse (`manage.py ai_gateway_sync`, сервис erp-ai-gateway); пусто — ИИ выключен
# (детерминированные пути остаются, как раньше без ключа провайдера).
LITELLM_BASE_URL = (os.environ.get("LITELLM_BASE_URL") or "").strip().rstrip("/")
LITELLM_API_KEY = (os.environ.get("LITELLM_API_KEY") or "").strip()
AI_IMPORT_ENABLED = (
    bool(LITELLM_BASE_URL and LITELLM_API_KEY) and os.environ.get("AI_IMPORT_ENABLED", "true").lower() == "true"
)
# Rows-per-chunk cap so a 10k-line spec is split into bounded LLM calls (token
# limits) and merged — keeps each request fast, cheap, and within output budget.
AI_IMPORT_CHUNK_ROWS = int(os.environ.get("AI_IMPORT_CHUNK_ROWS", "400"))
# ADR-0006 Move 3: minimum AI confidence (0–1) to AUTO-BIND a fuzzy catalog match into a draft КП.
# High by default — a confident bind into a seller-reviewed draft is safe; below it the line is left
# for the manual Smart Match. Exact GOST/MPN matches bypass this (they're deterministic, not fuzzy).
AI_DRAFT_MATCH_CONFIDENCE = float((os.environ.get("AI_DRAFT_MATCH_CONFIDENCE") or "0.9").strip() or "0.9")
# Таймаут одного HTTP-вызова шлюза (секунды). Вызовы идут только из очереди `ai` (Celery), но
# зависший ответ не должен держать воркер дольше лимита задачи; у алиасов в LiteLLM свои
# таймауты (60–120 с), этот — потолок со стороны ERP.
AI_REQUEST_TIMEOUT = float((os.environ.get("AI_REQUEST_TIMEOUT") or "130").strip() or "130")
# Повторы при сетевой ошибке/5xx шлюза — только у пакетного импорта Excel (process_excel_import);
# интерактивные задачи — одна попытка (платный вызов, пользователь просто нажмёт ещё раз).
AI_MAX_RETRIES = int((os.environ.get("AI_MAX_RETRIES") or "2").strip() or "2")
# Security audit #13: per-company daily safety cap on interactive AI jobs (a runaway
# script / abuse would otherwise run an unbounded model bill). This is a spend
# CIRCUIT-BREAKER, not a policy/tier limit — the ceiling is deliberately GENEROUS so a
# legitimate team never reaches it; enforced blanket across all AI features at the one
# enqueue choke-point. Counted per company per calendar day (settings.TIME_ZONE) from the
# persistent AIJob rows. 0 or negative disables the cap entirely (opt-out).
AI_DAILY_JOB_CAP_PER_COMPANY = int((os.environ.get("AI_DAILY_JOB_CAP_PER_COMPANY") or "300").strip() or "300")
# Бюджет ERP на день в USD (ARCHITECTURE §8): первый уровень — журнал вызовов ERP (ai.AICall,
# стоимость из заголовка шлюза, календарный день TIME_ZONE) проверяется ПЕРЕД каждым вызовом;
# второй — бюджет виртуального ключа ERP в LiteLLM (то же значение, сутки UTC). Превышение —
# код AI_BUDGET_EXCEEDED в результате задачи. 0 — без лимита. По умолчанию $1 — как
# `settings.budget.erp_daily_usd` консоли CRM (страница «Расходы»).
AI_DAILY_BUDGET_USD = float((os.environ.get("AI_DAILY_BUDGET_USD") or "1").strip() or "1")
# Hard byte cap before a file is sent to the model. Vision payloads (PDF/image) go
# as one base64 request, so an oversized file means a 413 + wasted spend — reject it
# early. Default 10 MB (the upload endpoint already caps the raw file at 20 MB).
AI_IMPORT_MAX_BYTES = int(os.environ.get("AI_IMPORT_MAX_BYTES", str(10 * 1024 * 1024)))

# ── КП: санитарные потолки ввода строки ─────────────────────────────────────
# Верхние границы на количество/цену строки КП. Это НЕ бизнес-лимиты, а защита
# от fat-finger / вставки в чужое поле: заявка с qty=1 500 000 или ценой в 10¹²
# искажает экономику КП и расчёт кредитов. Нижняя граница (0/1) уже на модели
# (MinValueValidator — KP-04); здесь только верхний санитарный потолок.
QUOTE_ITEM_MAX_QUANTITY = int(os.getenv("QUOTE_ITEM_MAX_QUANTITY", "1000000"))
QUOTE_ITEM_MAX_UNIT_PRICE = Decimal(os.getenv("QUOTE_ITEM_MAX_UNIT_PRICE", "10000000000"))

# Max line rows accepted in ONE transactional bulk-update of КП items (P0-4). A КП is a
# bounded document, so a batch far above the largest real КП is a malformed/abusive payload
# — reject it with QUOTE_ITEMS_BULK_TOO_LARGE rather than lock the quote row for a huge write.
QUOTE_ITEMS_BULK_MAX_ROWS = int(os.getenv("QUOTE_ITEMS_BULK_MAX_ROWS", "500"))

# Removed duplicate declarations (now at the top)

# Logging
# Set DJANGO_LOG_FORMAT=json in production to emit one structured JSON object
# per log line (with request_id correlation) for a log aggregator. Default
# stays human-readable for local development.
_LOG_FORMAT = os.environ.get("DJANGO_LOG_FORMAT", "console").strip().lower()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "core.logging.RequestIDFilter",
        },
        "redact_portal_token": {
            "()": "core.logging.RedactPortalTokenFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} [{request_id}] {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "json": {
            "()": "core.logging.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if _LOG_FORMAT == "json" else "verbose",
            "filters": ["request_id", "redact_portal_token"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    # httpx/httpcore на INFO печатают URL каждого запроса — секреты в адресе (ключ шлюза и т. п.)
    # не должны попадать в журнал; ошибки транспорта видны на WARNING.
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        # Логгер `django` из DEFAULT_LOGGING имеет СВОЙ обработчик `console` (при DEBUG=True): он печатает
        # `Gone: /api/portal/v1/auth/magic/<токен>` в stderr мимо нашего фильтра токена (FIX-15). Переопределяем:
        # всё идёт через наш `console` с RedactPortalTokenFilter (`mail_admins` не нужен: ADMINS не заданы).
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Validation Rules
INN_VALIDATION_REGEX = r"^\d{9}$"
# Uzbekistan phone: +998 followed by 9 digits (e.g. +998901234567).
UZ_PHONE_REGEX = r"^\+998\d{9}$"

# Email — backend can be explicitly overridden via EMAIL_BACKEND env var.
# Default: console in DEBUG, SMTP in production. For local testing with DEBUG=False
# and no real SMTP credentials, set EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
_default_email_backend = (
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", _default_email_backend)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.com")
