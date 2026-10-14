"""Email-каналы, логирование, Sentry и прочий хвост."""

import os

from .ai import *  # noqa: F401,F403 — последовательная композиция настроек

# ──────────────────────────────────────────────────────────────────────────
# Email channels — one SMTP/ESP config per purpose.
#
# Why channels: transactional (1:1 invites / password / documents) and marketing
# (digests / campaigns) SHOULD use different providers in production —
# reputation of transactional mail tanks when marketing messages get flagged.
# On day one, every channel falls back to the default SMTP above, so nothing
# breaks; override EMAIL_<CH>_* env vars when you add Mailgun/SES/SendGrid.
#
# Channel is chosen in code (services.py), not in admin UI — transport config
# is infra, not business data. Template text CAN be edited in admin later.
# ──────────────────────────────────────────────────────────────────────────


def _email_channel(prefix: str, *, default_from: str) -> dict:
    """Build one channel config, falling back to the global EMAIL_* defaults.

    prefix = 'TX' | 'MKT' | 'SYS' — matches env var naming:
    EMAIL_TX_HOST, EMAIL_TX_FROM, EMAIL_TX_USER, etc.
    """
    env = os.environ.get
    return {
        "backend": env(f"EMAIL_{prefix}_BACKEND") or EMAIL_BACKEND,
        "host": env(f"EMAIL_{prefix}_HOST") or EMAIL_HOST,
        "port": int(env(f"EMAIL_{prefix}_PORT") or EMAIL_PORT),
        "username": env(f"EMAIL_{prefix}_USER") or EMAIL_HOST_USER,
        "password": env(f"EMAIL_{prefix}_PASSWORD") or EMAIL_HOST_PASSWORD,
        "use_tls": (env(f"EMAIL_{prefix}_USE_TLS") or str(EMAIL_USE_TLS)) == "True",
        "from_email": env(f"EMAIL_{prefix}_FROM") or default_from,
    }


EMAIL_CHANNELS = {
    # Setup-password, invitations, documents.
    "transactional": _email_channel("TX", default_from=DEFAULT_FROM_EMAIL),
    # Digests, campaigns, broadcasts. Not used yet — reserved.
    "marketing": _email_channel(
        "MKT",
        default_from=os.environ.get("EMAIL_MKT_FROM", DEFAULT_FROM_EMAIL),
    ),
    # Platform-internal alerts to ops (failed jobs, error reports).
    "system": _email_channel(
        "SYS",
        default_from=os.environ.get("EMAIL_SYS_FROM", DEFAULT_FROM_EMAIL),
    ),
}

# Frontend URL for email links (password setup, invitations, etc.)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# Support contact printed in the footer of every transactional email (was hardcoded in
# templates/emails/base.html). Overridable per deployment.
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@example.com")


# ──────────────────────────────────────────────────────────────────────────
# Observability — Sentry error reporting
#
# Completely inert unless SENTRY_DSN is set, so this is safe to ship to every
# environment. Set SENTRY_DSN (+ optional SENTRY_ENVIRONMENT,
# SENTRY_TRACES_SAMPLE_RATE) in the deploy secrets to turn it on. When live,
# every unhandled 500 / Celery task failure lands in Sentry with a stack trace
# and request context — so a break is seen in a dashboard, not via a frustrated
# client. See Docs/dev/ops/observability.md.
# ──────────────────────────────────────────────────────────────────────────
SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    from core.sentry_scrub import scrub_event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        # Performance tracing is opt-in and off by default (0.0) to control cost.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,
        # send_default_pii only stops Sentry's OWN auto-PII; domain PII we put into an
        # event (ИНН/phone in request.data, extra, breadcrumbs) is masked here (SEC-tail).
        before_send=scrub_event,
    )
