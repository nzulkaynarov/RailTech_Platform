"""Ссылки в письмах, логирование, Sentry и прочий хвост."""

import os

from .ai import *  # noqa: F401,F403 — последовательная композиция настроек

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

    from core.log_mask import mask_breadcrumb
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
        # FIX-66b: интеграции httpx/requests/логгеров пишут URL (токен Bot API, подпись S3) в хлебные крошки.
        before_breadcrumb=mask_breadcrumb,
    )
