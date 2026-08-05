"""AI-слой: модель, лимиты импорта, санитарные потолки КП (ARCH-01)."""

import os
from decimal import Decimal

from .infra import *  # noqa: F401,F403 — последовательная композиция настроек

# ── AI заявка normalisation ─────────────────────────────────────────────────
# A client may upload ANY file (Excel / CSV / PDF / image / pasted text); Claude
# extracts the line items into our canonical schema (name / quantity / unit /
# note). The buyer ALWAYS reviews the result before submitting — the AI never
# writes a final заявка unattended. Disabled automatically when no API key is set
# (the deterministic keyword parser remains the fallback).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_IMPORT_MODEL = os.environ.get("AI_IMPORT_MODEL", "claude-opus-4-8")
AI_IMPORT_ENABLED = bool(ANTHROPIC_API_KEY) and os.environ.get("AI_IMPORT_ENABLED", "true").lower() == "true"
# Rows-per-chunk cap so a 10k-line spec is split into bounded LLM calls (token
# limits) and merged — keeps each request fast, cheap, and within output budget.
AI_IMPORT_CHUNK_ROWS = int(os.environ.get("AI_IMPORT_CHUNK_ROWS", "400"))
# ADR-0006 Move 3: minimum AI confidence (0–1) to AUTO-BIND a fuzzy catalog match into a draft КП.
# High by default — a confident bind into a seller-reviewed draft is safe; below it the line is left
# for the manual Smart Match. Exact GOST/MPN matches bypass this (they're deterministic, not fuzzy).
AI_DRAFT_MATCH_CONFIDENCE = float((os.environ.get("AI_DRAFT_MATCH_CONFIDENCE") or "0.9").strip() or "0.9")
# ARCH-01: cap how long a single synchronous LLM call may hold a request worker.
# The interactive AI endpoints (catalog-match / pre-flight / КП-diff / chat-assist
# / PIM-enrich / contract-extract / conversational builder) call Claude IN the
# request path on Daphne; the anthropic SDK's DEFAULT read timeout is 600s, so one
# slow/hung completion could pin a worker for up to 600s × (1 + max_retries) —
# ~30 min worst case — starving all other requests. Cap the per-attempt timeout
# well below that but comfortably above normal Structured-Outputs latency (a few
# seconds). The bulk Excel import shares this client but runs off the request path
# (Celery: sourcing.tasks.process_excel_import), so the cap is safe there too.
AI_REQUEST_TIMEOUT = float((os.environ.get("AI_REQUEST_TIMEOUT") or "60").strip() or "60")
AI_MAX_RETRIES = int((os.environ.get("AI_MAX_RETRIES") or "2").strip() or "2")
# Security audit #13: per-company daily safety cap on interactive AI jobs (a runaway
# script / abuse would otherwise run an unbounded Anthropic bill). This is a spend
# CIRCUIT-BREAKER, not a policy/tier limit — the ceiling is deliberately GENEROUS so a
# legitimate team never reaches it; enforced blanket across all 8 AI features at the one
# enqueue choke-point. Counted per company per calendar day (settings.TIME_ZONE) from the
# persistent AIJob rows. 0 or negative disables the cap entirely (opt-out).
AI_DAILY_JOB_CAP_PER_COMPANY = int((os.environ.get("AI_DAILY_JOB_CAP_PER_COMPANY") or "300").strip() or "300")
# P1 two-tier cap: the tighter daily ceiling for a company WITHOUT an operational subscription.
# The free floor (ai.match / ai.preflight) and the ungated wedge features (extract / compose) are
# usable by unsubscribed tenants, so a free company still needs a runaway-bill fuse — just a lower
# one than a paying tenant. 0 or negative disables the free-tier cap entirely (opt-out).
AI_DAILY_JOB_CAP_FREE = int((os.environ.get("AI_DAILY_JOB_CAP_FREE") or "30").strip() or "30")
# Tier-aware daily AI ceiling: map each subscription plan to its daily AI-job allowance
# (Старт / Про / Безлимит). The DB plan CODES stay stable (BASIC/STANDARD/PREMIUM) — only
# the allowance number is attached here, tunable via env. 0 or negative = UNLIMITED (the
# Безлимит tier, PREMIUM). A per-company CompanyEntitlement(ai.daily_cap).limit override
# (set by an operator in React Admin) wins over these plan defaults. A company with NO
# operational subscription falls back to AI_DAILY_JOB_CAP_FREE above.
AI_DAILY_CAP_BASIC = int((os.environ.get("AI_DAILY_CAP_BASIC") or "75").strip() or "75")  # Старт
AI_DAILY_CAP_STANDARD = int((os.environ.get("AI_DAILY_CAP_STANDARD") or "300").strip() or "300")  # Про
AI_DAILY_CAP_PREMIUM = int((os.environ.get("AI_DAILY_CAP_PREMIUM") or "0").strip() or "0")  # Безлимит (0 = off)
# R4 §7.4: `/me` показывает остаток дневного лимита ИИ. Разрешение ПОТОЛКА (подписка +
# энтайтлмент-override) — это запросы в базу на каждый `/me`, а сам потолок меняется раз в
# месяцы; кэшируем его на столько секунд. Израсходованное НЕ кэшируется никогда — это как раз
# то число, которое меняется. Кэш только на показе: предохранитель в enqueue считает потолок
# напрямую. 0 отключает кэш (тесты, отладка).
AI_DAILY_USAGE_CACHE_TTL = int((os.environ.get("AI_DAILY_USAGE_CACHE_TTL") or "60").strip() or "60")
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
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
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

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@railtech.uz")
