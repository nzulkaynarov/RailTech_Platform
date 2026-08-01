"""DRF, JWT + refresh-cookie, login-lockout, Spectacular."""

import os
from datetime import timedelta

from .project import *  # noqa: F401,F403 — последовательная композиция настроек

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": [
        # Production: all endpoints require auth by default
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "200/minute",
        "lead_submit": "5/minute",
        "import_upload": "10/hour",
        # Anti-abuse on unauthenticated/sensitive auth endpoints (the global anon
        # 20/min is far too loose to stop e.g. password-reset email bombing).
        "password_reset": "5/hour",  # forgot-password, per IP
        "password_reset_email": "3/hour",  # forgot-password, per TARGET email (cross-IP victim shield)
        "register": "5/hour",  # account/verification-email spam, per IP
        "client_invite": "20/hour",  # seller invites an offline client to register (CRM Phase D), per user
        "password_set": "20/hour",  # setup/reset-password token submission, per IP (brute-force)
        "login": "10/minute",  # token obtain + 2FA code step, per IP (brute-force; lenient enough for typos)
        "two_factor": "10/minute",  # 2FA setup/verify/disable, per user (stolen-session code brute-force)
        "public_quote": "30/minute",  # unauthenticated КП-by-token view; blunts token brute-forcing
        "public_document": "30/minute",  # unauthenticated ISSUED-document-by-token view; blunts token brute-forcing
        "document_send_email": "20/hour",  # F2-3: authenticated document email dispatch; blunts spam/phishing relay
        "document_preview": "60/minute",  # F3-1/III-5: template live-preview sanitises+renders up to 100k per call
        "public_quote_view": "60/minute",  # Wave A: КП page «viewed» beacon (deduped server-side)
        "public_quote_code": "5/hour",  # Wave A: request КП acceptance code, per IP — blunts email bombing
        "public_quote_accept": "10/minute",  # Wave A: verify code / reject, per IP — blunts code brute-force
        "ai_match": "20/minute",  # AI catalog-match endpoint — each call is a paid Claude request
        "ai_preflight": "20/minute",  # AI заявка pre-flight quality check — each call is a paid Claude request
        "ai_enrich": "20/minute",  # AI PIM product enrichment — each call is a paid Claude request
        "ai_chat": "20/minute",  # AI deal-chat reply assist — each call is a paid Claude request
        "ai_diff": "20/minute",  # AI КП-vs-заявка diff — each call is a paid Claude request
        "ai_extract": "20/minute",  # AI PDF contract/invoice extraction — each call is a paid Claude request
        "ai_compose": "20/minute",  # AI conversational заявка builder — each call is a paid Claude request
        "ai_draft": "20/minute",  # AI draft-КП build — paid Claude match + a new Quote row per call
    },
    # SEC-04: number of trusted reverse proxies that set X-Forwarded-For before Django.
    # Prod/staging = 1 (host Caddy OVERWRITES XFF with the client IP — see
    # deploy/caddy/b2b.railtech.uz.caddy). Dev = 0 (no proxy; XFF is client-forgeable
    # and must be ignored, otherwise per-IP throttles are trivially bypassed).
    # Tolerate an empty/blank env value (e.g. DRF_NUM_PROXIES= in a .env) so a
    # malformed override fails safe to 0 instead of crashing app boot on int("").
    "NUM_PROXIES": int((os.environ.get("DRF_NUM_PROXIES") or "0").strip() or "0"),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # API versioning (F2.6): formal contract instead of a hardcoded "v1". Routes are
    # still served under /api/v1/, so request.version resolves to DEFAULT_VERSION;
    # an unknown version simply has no route (404). When v2 is introduced, add it to
    # ALLOWED_VERSIONS and mount /api/v2/ — request.version then drives per-version logic.
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "VERSION_PARAM": "version",
}

# API deprecation / Sunset policy (RFC 8594). Map a version → ISO sunset date to
# start emitting `Deprecation: true` + `Sunset: <date>` headers on its responses
# (core.versioning.SunsetHeaderMiddleware). Empty = nothing deprecated yet.
API_SUNSET = {}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# Refresh token in an HttpOnly cookie (F2.1): the refresh token never reaches JS, so
# XSS can't exfiltrate it. The access token still rides the response body (kept in
# memory by the SPA, never localStorage). Cookie is scoped to the auth path so it's
# only sent to /token/refresh/ and /logout/, not every API call.
REFRESH_COOKIE_NAME = os.environ.get("REFRESH_COOKIE_NAME", "refresh_token")
REFRESH_COOKIE_PATH = "/api/v1/auth/"
# HTTPS-only in prod. Decoupled from DEBUG so a prod-like local stack (DEBUG=False)
# served over plain http can still set REFRESH_COOKIE_SECURE=False and have the
# browser send the cookie. Defaults to secure unless DEBUG.
REFRESH_COOKIE_SECURE = os.environ.get("REFRESH_COOKIE_SECURE", "false" if DEBUG else "true").strip().lower() == "true"
REFRESH_COOKIE_SAMESITE = os.environ.get("REFRESH_COOKIE_SAMESITE", "Lax")
REFRESH_COOKIE_MAX_AGE = int(SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

# SEC-06: per-account login lockout (accounts/services/login_guard.py). Layered on
# top of the per-IP `login` throttle to blunt DISTRIBUTED brute-force against a
# single account. The lock trips on the number of DISTINCT source IPs that fail
# for an email within the window — NOT on raw attempts, so a single IP (already
# capped by the per-IP throttle) can never lock a victim (that would be a cheap
# targeted DoS since B2B emails are semi-public). 10 distinct IPs failing one
# account in 15 min is a clear distributed-attack signature with ~zero false
# positives. Blank/malformed env values fail safe to the default.
LOGIN_LOCKOUT_DISTINCT_IPS = int((os.environ.get("LOGIN_LOCKOUT_DISTINCT_IPS") or "10").strip() or "10")
LOGIN_LOCKOUT_WINDOW = int((os.environ.get("LOGIN_LOCKOUT_WINDOW") or "900").strip() or "900")
LOGIN_LOCKOUT_COOLDOWN = int((os.environ.get("LOGIN_LOCKOUT_COOLDOWN") or "900").strip() or "900")

# DRF Spectacular (API Documentation)
SPECTACULAR_SETTINGS = {
    "TITLE": "RailTech B2B API",
    "DESCRIPTION": (
        "B2B marketplace API for railway equipment procurement in Uzbekistan. "
        "Supports deal lifecycle management, quoting, product catalog (PIM), "
        "KYC verification, Excel imports, and real-time notifications via WebSocket."
    ),
    "VERSION": "1.0.0",
    "CONTACT": {"name": "RailTech API Support", "email": "api@railtech.com"},
    "LICENSE": {"name": "Proprietary"},
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v[0-9]+/",
    "TAGS": [
        {"name": "Auth", "description": "Registration, password setup, JWT tokens"},
        {"name": "Accounts", "description": "Users, companies, KYC, team management"},
        {"name": "Catalog", "description": "Products (PIM), categories, equipment groups, supplier offers"},
        {"name": "CRM", "description": "Deals, quotes, quote items, messages, activity logs"},
        {"name": "Sourcing", "description": "Excel imports, catalog imports, sourcing requests"},
        {"name": "Master Data", "description": "Countries, currencies, units of measure, delivery basis"},
        {"name": "Notifications", "description": "User notifications with read/unread tracking"},
        {"name": "Analytics", "description": "Dashboard KPIs, CRM analytics, page stats"},
        {"name": "System", "description": "Health checks, system settings"},
    ],
}
