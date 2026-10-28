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
    # Только JSON (M1-ERP-07). Browsable API DRF по умолчанию включён и в проде: на
    # `Accept: text/html` любой эндпоинт с открытым чтением рисовал HTML-форму записи, а в её
    # выпадающих списках — справочники целиком (например, все компании-поставщики на
    # `/catalog/offers/` анониму). Документация API — Swagger/Redoc по схеме.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Неприемлемый `Accept` (браузер на публичной странице КП) — JSON, а не 406.
    "DEFAULT_CONTENT_NEGOTIATION_CLASS": "core.negotiation.JSONFallbackContentNegotiation",
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
        # Запросы CRM к integration с валидным сервисным токеном (Q-FIX30-4): ключ — токен, не адрес; предохранитель от
        # зацикленного клиента, а не ограничение работы бота и карточек (integration/throttles.py).
        "integration": os.environ.get("INTEGRATION_RATE", "300/minute"),
        # Попытки ввода кода сопряжения с CRM (M3-ERP-05, integration/throttles.py): код 59 бит и живёт 15 минут.
        "pairing": os.environ.get("PAIRING_RATE", "10/hour"),
        "import_upload": "10/hour",
        # Anti-abuse on unauthenticated/sensitive auth endpoints (the global anon
        # 20/min is far too loose to stop e.g. password-reset email bombing).
        "password_reset": "5/hour",  # forgot-password, per IP
        "password_reset_email": "3/hour",  # forgot-password, per TARGET email (cross-IP victim shield)
        "password_set": "20/hour",  # setup/reset-password token submission, per IP (brute-force)
        # FIX-64 (N-2): обновление сессии (refresh, HttpOnly-cookie) — свой счётчик по IP: общий анонимный 20/мин
        # его съедал (серия переходов с одного адреса/NAT → 429 → выход на форму входа). Подбор тут не выгоден:
        # нужен действующий refresh-токен.
        "token_refresh": os.environ.get("TOKEN_REFRESH_RATE", "60/minute"),
        "login": "10/minute",  # token obtain + 2FA code step, per IP (brute-force; lenient enough for typos)
        "two_factor": "10/minute",  # 2FA setup/verify/disable, per user (stolen-session code brute-force)
        "public_quote": "30/minute",  # unauthenticated КП-by-token view; blunts token brute-forcing
        "public_document": "30/minute",  # unauthenticated ISSUED-document-by-token view; blunts token brute-forcing
        "document_send_email": "20/hour",  # F2-3: authenticated document email dispatch; blunts spam/phishing relay
        "email_test_send": "10/hour",  # FIX-42: тестовое письмо по шаблону уходит по настоящему каналу, на любой адрес
        "document_preview": "60/minute",  # F3-1/III-5: template live-preview sanitises+renders up to 100k per call
        "public_quote_view": "60/minute",  # Wave A: КП page «viewed» beacon (deduped server-side)
        "public_quote_code": "5/hour",  # Wave A: request КП acceptance code, per IP — blunts email bombing
        "public_quote_accept": "10/minute",  # Wave A: verify code / reject, per IP — blunts code brute-force
        "ai_match": "20/minute",  # AI catalog-match endpoint — each call is a paid Claude request
        "ai_preflight": "20/minute",  # AI заявка pre-flight quality check — each call is a paid Claude request
        "ai_enrich": "20/minute",  # AI PIM product enrichment — each call is a paid Claude request
        "ai_diff": "20/minute",  # AI КП-vs-заявка diff — each call is a paid Claude request
        "ai_extract": "20/minute",  # AI PDF contract/invoice extraction — each call is a paid Claude request
        "ai_compose": "20/minute",  # AI conversational заявка builder — each call is a paid Claude request
        "ai_draft": "20/minute",  # AI draft-КП build — paid Claude match + a new Quote row per call
        "mcp": "120/minute",  # erp-mcp (FIX-12/36): на компанию из X-Agent-Context (mcp/gate.py); tools/call ≈ 3 запроса
        # Портал (FIX-15, P-14): общий анонимный 20/мин по IP на него не распространяется (portal/throttles.py).
        "portal_session": os.environ.get("PORTAL_SESSION_RATE", "120/minute"),  # на сессию; экран Cabinet = пачка GET
        "portal_login": os.environ.get(
            "PORTAL_LOGIN_RATE", "10/minute"
        ),  # вход без сессии, на IP (magic-link, initData)
        "portal_accept": os.environ.get("PORTAL_ACCEPT_RATE", "10/minute"),  # акцепт КП с кодом, на сессию
    },
    # SEC-04: number of trusted reverse proxies that set X-Forwarded-For before Django.
    # Prod/staging = 1 (host Caddy OVERWRITES XFF with the client IP — see
    # deploy/caddy). Dev = 0 (no proxy; XFF is client-forgeable
    # and must be ignored, otherwise per-IP throttles are trivially bypassed).
    # Tolerate an empty/blank env value (e.g. DRF_NUM_PROXIES= in a .env) so a
    # malformed override fails safe to 0 instead of crashing app boot on int("").
    "NUM_PROXIES": int((os.environ.get("DRF_NUM_PROXIES") or "0").strip() or "0"),
    # N2: клиент может попросить больше строк (?page_size=), верхняя граница 200 —
    # см. core/pagination.py (раньше page_size молча игнорировался и списки резались на 20).
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "core.openapi.ErpAutoSchema",
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
    "TITLE": "ERP API",
    "DESCRIPTION": (
        "ERP Platform API. "
        "Supports deal lifecycle management, quoting, product catalog (PIM), "
        "Excel imports, and real-time notifications via WebSocket."
    ),
    "VERSION": "1.1.0",
    "CONTACT": {"name": "ERP API Support", "email": "support@example.com"},
    "LICENSE": {"name": "Proprietary"},
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Тела отказов 4xx/5xx без явной схемы — общий компонент ErrorDetail (core/openapi.py, D2-0).
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "core.openapi.describe_error_responses",
    ],
    "SCHEMA_PATH_PREFIX": "/api/v[0-9]+/",
    # Одни и те же словари каталога у карточки и у настроек компании (M1-ERP-07) — одно имя enum.
    "ENUM_NAME_OVERRIDES": {
        "PriceVisibilityEnum": "catalog.constants.PriceVisibility",
        "FulfillmentPolicyEnum": "catalog.constants.FulfillmentPolicy",
        # Те же наборы значений в служебных сериализаторах (приглашение контакта, офлайн-клиент, сопряжение с CRM) —
        # одно имя, иначе drf-spectacular придумывает хешированные (D2-0, выгрузка без предупреждений).
        "ContactPreferredChannelEnum": ["email", "telegram", "both"],
        "LanguageEnum": ["ru", "uz", "en"],
        "SecretSourceEnum": ["db", "env", "none"],
        # Проекты (D2-5): слова статусов SPEC-v3 §2.4 у договора, счёта и акта — свои имена, а не хеши по полю `status`.
        "ProjectContractStatusEnum": [
            "project",
            "client_agreed",
            "issued_at_operator",
            "signed",
            "rejected",
            "cancelled",
        ],
        "ProjectInvoiceStatusEnum": ["to_issue", "issued", "partial", "paid", "overdue", "cancelled"],
        "ProjectActStatusEnum": ["project", "returned", "issued", "signed", "cancelled"],
        # D2-3: «Номенклатура и поставщики» — одноимённые поля `kind` и `unit` у разных схем.
        "DeskItemKindEnum": ["stock", "on_order", "service_fixed", "service_milestones", "service_time"],
        "BrigadeKindEnum": ["brigade", "person", "subcontractor"],
        "TechDocKindEnum": ["tz", "drawing", "certificate", "pnr", "other"],
        "CrewRateUnitEnum": ["day", "hour"],
        # D2-1 «Расчёт по заявке» (crm.serializers.calc): наборы значений с явными именами.
        "CalcVisaStateEnum": "crm.serializers.calc.VISA_STATES",
        "CalcStateEnum": "crm.serializers.calc.CALC_STATES",
        "CalcLineKindEnum": "crm.serializers.calc.LINE_KINDS",
        "CalcItemKindEnum": "crm.serializers.calc.ITEM_KINDS",
        # D2-2 «Склад»: статусы заказа поставщику, резерва и запроса цены.
        "SupplierOrderStatusEnum": "supply.serializers.ORDER_STATUSES",
        "StockReservationStatusEnum": "inventory.serializers.RESERVATION_STATUSES",
        "PriceRequestStatusEnum": ["sent", "failed"],
        "SupplierOrderReceiptStateEnum": "supply.serializers.RECEIPT_STATES",
    },
    "TAGS": [
        {"name": "Auth", "description": "Login, password setup by invitation, JWT tokens"},
        {"name": "Accounts", "description": "Users, companies, team management"},
        {"name": "Catalog", "description": "Products (PIM), categories, equipment groups, supplier offers"},
        {"name": "CRM", "description": "Deals, quotes, quote items, activity logs"},
        {"name": "Sourcing", "description": "Excel imports, catalog imports, sourcing requests"},
        {"name": "Master Data", "description": "Countries, currencies, units of measure, delivery basis"},
        {"name": "Notifications", "description": "User notifications with read/unread tracking"},
        {"name": "Analytics", "description": "Dashboard KPIs, CRM analytics, page stats"},
        {"name": "System", "description": "Health checks, system settings"},
    ],
}

# ─── Секреты шва CRM ↔ ERP (CONTRACTS §0, §2, §3, §5, §6) ─────────────────────
# Значений по умолчанию нет (FIX-01, аудит S-1/I-1): известный всем ключ = открытый шов. Пусто —
# функция закрыта (интеграционный API отвечает 401, вебхуки не уходят, MCP — 401, SSO — 503);
# без DEBUG пустой секрет — ошибка старта. Значения — из .env через infra/compose.


def _secret_list(name: str) -> list[str]:
    """До двух активных значений через запятую — ротация без простоя."""
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


# Сервисный токен направления CRM → ERP (OpenAPI erp-integration.yaml).
SERVICE_TOKEN_CRM_TO_ERP = _secret_list("SERVICE_TOKEN_CRM_TO_ERP")
ERP_VERSION = os.environ.get("ERP_VERSION", "0.1.0")
# Сопряжение с CRM (M3-ERP-05): срок жизни кода (сек) и переходный период ротации — сколько ещё действует прежний
# токен CRM→ERP после «Обновить ключи» (сек).
PAIRING_CODE_TTL_SECONDS = int(os.environ.get("PAIRING_CODE_TTL_SECONDS", "900"))
PAIRING_ROTATION_GRACE_SECONDS = int(os.environ.get("PAIRING_ROTATION_GRACE_SECONDS", "3600"))

# Шина событий rt_bus (B3, ADR-0014): адреса подписчиков и пути контрактов задают RT_BUS_* (читает сама библиотека,
# docs/architecture/rt-bus.md §2) — в образе: RT_BUS_CONTRACTS_DIR=/opt/rt/contracts/events, RT_BUS_SUBSCRIPTIONS=…/bus/subscriptions.yaml.
# Вебхуков ERP → CRM нет. Секрет вебхуков СОПРЯЖЕНИЯ — строка; для ротации без простоя допускается список через запятую:
# первое значение текущее. Он нужен шине как источник направленных секретов пары CRM ↔ ERP, если `RT_BUS_SECRET_ERP_CRM` /
# `RT_BUS_SECRET_CRM_ERP` не заданы (CONTRACTS §9, `integration.bus.pair_secrets`); сам по сети не ходит.
ERP_WEBHOOK_SECRET = os.environ.get("ERP_WEBHOOK_SECRET", "").strip()

# erp-mcp: ключ HMAC-SHA256 заголовка X-Agent-Context (срок 60 с).
ERP_MCP_CONTEXT_KEY = os.environ.get("ERP_MCP_CONTEXT_KEY", "").strip()
# erp-mcp (FIX-36): путь к packages/contracts/mcp-tools.json; пусто — /packages/contracts/mcp-tools.json
# (монтируется в compose и в контейнер тестов), затем поиск вверх от кода (запуск из клона репозитория).
ERP_MCP_TOOLS_PATH = os.environ.get("ERP_MCP_TOOLS_PATH", "").strip()

# SSO сотрудника CRM ↔ ERP (docs/architecture/sso-token.md): общий секрет JWT HS256, ротация — через запятую.
PLATFORM_SSO_SECRET = _secret_list("PLATFORM_SSO_SECRET")

_MISSING_SEAM_SECRETS = [
    name
    for name, value in (
        ("SERVICE_TOKEN_CRM_TO_ERP", SERVICE_TOKEN_CRM_TO_ERP),
        ("ERP_WEBHOOK_SECRET", _secret_list("ERP_WEBHOOK_SECRET")),
        ("ERP_MCP_CONTEXT_KEY", ERP_MCP_CONTEXT_KEY),
        ("PLATFORM_SSO_SECRET", PLATFORM_SSO_SECRET),
    )
    if not value
]
if _MISSING_SEAM_SECRETS and not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Seam secrets are required when DJANGO_DEBUG is off: " + ", ".join(_MISSING_SEAM_SECRETS)
    )
CRM_FRONTEND_URL = os.environ.get("CRM_FRONTEND_URL", "http://crm.localhost").rstrip("/")
# Переход CRM ↔ ERP выключен до волны 1 исправлений (FIX-03, аудит S-2/S-3): обмен токена сейчас
# небезопасен. Включает владелец после FIX-10/FIX-11 (PLATFORM_SSO_ENABLED=true).
PLATFORM_SSO_ENABLED = os.environ.get("PLATFORM_SSO_ENABLED", "false").strip().lower() == "true"
