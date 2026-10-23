"""ASGI/Channels, middleware, CORS/CSRF, cookies и security-заголовки, шаблоны."""

import os

from .apps import *  # noqa: F401,F403 — последовательная композиция настроек

# ASGI Support for Channels (real-time notifications)
ASGI_APPLICATION = "core.asgi.application"

# Redis Channel Layer — на `redis-broker` (БД 2), не на кэше: сообщения слоя нельзя вытеснять (S0-2).
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_CHANNELS_URL", "redis://redis-broker:6379/2")],
            "capacity": 300,
            "expiry": 60,
        },
    },
}

MIDDLEWARE = [
    "core.logging.RequestIDMiddleware",
    # Журнал запросов (Daphne запущен с -v 0: его access-лог пишет токен ссылки входа мимо фильтров, FIX-15).
    "core.logging.AccessLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Stamps Content-Security-Policy on responses (protects Unfold /admin/ HTML;
    # no-op on JSON). Report-Only by default — see core/csp.py. The public SPA's
    # CSP is mirrored on the host Caddy (deploy/caddy).
    "core.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    # L0 (spec-bilingual-ru-en): активация языка запроса по Accept-Language, который SPA
    # шлёт из i18n.language. БЕЗ него ~1500 gettext_lazy по проекту всегда рендерили
    # русский источник — слой i18n был декоративным. Канонная позиция Django: после
    # SessionMiddleware, до CommonMiddleware. Добавляет `Vary: Accept-Language` — именно
    # тот заголовок, по которому уже варьируются кэшируемые справочники.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Adds RFC 8594 Deprecation/Sunset headers for deprecated API versions (F2.6).
    "core.versioning.SunsetHeaderMiddleware",
    # Портал: изменяющие запросы только JSON + обязательный Idempotency-Key (FIX-15, C-12). До IdempotencyMiddleware.
    "portal.middleware.PortalRequestGuardMiddleware",
    # Innermost — wraps the view so it captures/replays the rendered response (F2.4).
    "core.idempotency.IdempotencyMiddleware",
]

# Idempotency-Key replay window + max in-flight lock (Sprint D / F2.4).
IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", str(24 * 3600)))
IDEMPOTENCY_LOCK_SECONDS = int(os.environ.get("IDEMPOTENCY_LOCK_SECONDS", "90"))

_env_cors = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True
# Dev-источники (Vite, `*.localhost`) — только при DEBUG=True. На DEBUG=False список строится из настроек:
# origin'ы Cabinet (CABINET_ORIGIN) и CORS_ALLOWED_ORIGINS из окружения; `localhost` в проде не пускаем (FIX-15, P-18).
_DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://cabinet.localhost",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
]
_cors_origins = [*(_DEV_CORS_ORIGINS if DEBUG else []), *CABINET_ORIGINS, *_env_cors]
CORS_ALLOWED_ORIGINS = list(dict.fromkeys(_cors_origins))  # без дублей, порядок сохраняется

# Allow our custom request headers through CORS preflight (cross-origin dev). Without
# these a credentialed request carrying them is blocked: Idempotency-Key (F2.4), If-Match
# (F2.5 optimistic locking). Prod is same-origin (no preflight) but this keeps cross-origin
# dev honest.
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key", "if-match", "accept-language")
# Let the SPA read these response headers cross-origin.
CORS_EXPOSE_HEADERS = ["ETag", "Idempotent-Replay", "Deprecation", "Sunset"]

_env_csrf = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    *_env_csrf,
]

# Production Cookie & Session Settings — only for real production domains (behind HTTPS nginx)
# On localhost (even with DEBUG=False) these must NOT be set, otherwise cookies
# are scoped to production domain and require HTTPS, breaking local admin login.
_is_real_production = not DEBUG and os.environ.get("PRODUCTION", "False").lower() == "true"

# Security headers — always enabled (safe for localhost too)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    # SEC-09: safe on any origin (no domain/HTTPS coupling) — not prod-gated.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

# SEC-09: the PRODUCTION gate stays (DEBUG=False over plain http is a legit local
# prod-like flow — Secure cookies + domain would break it), but a box
# that FORGOT the flag must not run silently without secure cookies/HSTS.
if not DEBUG and not _is_real_production:
    import warnings

    warnings.warn(
        "DJANGO_DEBUG=False but PRODUCTION!=true: secure-cookie/HSTS settings are OFF. "
        "Set PRODUCTION=true on any internet-facing deployment.",
        RuntimeWarning,
        stacklevel=1,
    )

if _is_real_production:
    if os.environ.get("SESSION_COOKIE_DOMAIN"):
        SESSION_COOKIE_DOMAIN = os.environ["SESSION_COOKIE_DOMAIN"]
    if os.environ.get("CSRF_COOKIE_DOMAIN"):
        CSRF_COOKIE_DOMAIN = os.environ["CSRF_COOKIE_DOMAIN"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HTTPS enforcement — opt-in via env so DEBUG=False can still be used for local testing
    # with remote DB. Enable these in real production deployment (behind HTTPS nginx).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "False").lower() == "true"

    # HSTS — opt-in. Only enable when SSL is fully configured and you are ready
    # for browsers to cache the "HTTPS-only" policy. Do NOT enable for localhost.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "False").lower() == "true"


ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
