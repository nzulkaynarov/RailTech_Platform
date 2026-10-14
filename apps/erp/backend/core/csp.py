"""
Content-Security-Policy middleware for the Django app (API + Unfold /admin/).

Why a custom middleware instead of django-csp:
    django-csp is not (and need not be) a dependency — our policy is small and a
    ~30-line middleware expresses it more clearly than the per-view nonce
    machinery django-csp pulls in. Switch to django-csp only if the policy ever
    grows nonces / per-view overrides.

Where CSP actually comes from on the prod host (IMPORTANT — read before editing):
    On the VPS the **host Caddy** (deploy/caddy) sets a
    site-level `header { Content-Security-Policy ... }`. In Caddy a site-level
    header directive applies to EVERY response on the origin — the React SPA it
    serves directly AND the /api + /admin responses it reverse-proxies to
    Django — and it REPLACES any header the backend already set. So on prod,
    Caddy's CSP is the effective policy for the whole origin and the header this
    middleware sets is overwritten (verified 2026-07-03:
    `curl -I https://example.com/admin/login/` returns Caddy's policy).

    This middleware is therefore the FALLBACK, not the prod source of truth: it
    stamps a CSP on deploys that have no fronting proxy setting one (local dev,
    a bare staging box, `runserver`). Keep CSP_POLICY in sync with the Caddy
    block so the fallback matches what prod actually enforces.

Policy rationale (verified against the running Unfold /admin/, 2026-07-08):
    Unfold/Django admin loads its JS from external /static/ files (zero inline
    <script>), BUT it ships Alpine.js, which compiles x-data/x-show/x-cloak
    directive expressions with new Function() at RUNTIME — and that needs
    'unsafe-eval' in script-src, which external-file loading ('self') does NOT
    cover. So the /admin/ path gets CSP_POLICY_ADMIN (script-src 'self'
    'unsafe-eval'); the SPA + /api keep the strict CSP_POLICY (a Vite build never
    evals). The admin also uses inline `style=` attributes and data:/blob: images,
    so style-src keeps 'unsafe-inline' and img/worker keep data:/blob:. Prod
    enforces the equivalent via the Caddy /admin/* override — keep the two in sync.

Posture:
    Defaults to **Content-Security-Policy-Report-Only** so a fallback deploy can
    only warn, never break, on a missed asset. Set env CSP_REPORT_ONLY=false to
    enforce. On the prod host the mode chosen here is moot — Caddy's enforcing
    header wins regardless.
"""

import os

# Single source of truth for the policy string — mirror of the Caddy edge policy
# (minus the SPA-only origins Django's /api + /admin never need). self-only for
# scripts (verified: Unfold admin has no inline scripts); 'unsafe-inline' kept for
# styles only (admin inline style= attributes); no third-party origins.
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)

# Unfold /admin/ ships Alpine.js, which evaluates its x-* directives with
# new Function() at runtime → needs 'unsafe-eval'. Scoped to /admin/ so the SPA +
# /api keep the strict policy above. Mirrors the Caddy @admin_csp override.
CSP_POLICY_ADMIN = CSP_POLICY.replace("script-src 'self';", "script-src 'self' 'unsafe-eval';")

# Report-Only by default — non-breaking first rollout. Set CSP_REPORT_ONLY=false
# in prod env once Unfold /admin/ is confirmed clean to switch to enforcing.
_REPORT_ONLY = os.environ.get("CSP_REPORT_ONLY", "true").strip().lower() != "false"
CSP_HEADER_NAME = "Content-Security-Policy-Report-Only" if _REPORT_ONLY else "Content-Security-Policy"


class ContentSecurityPolicyMiddleware:
    """Stamp a Content-Security-Policy[-Report-Only] header on every response.

    Does not overwrite a CSP header already set by an inner middleware or view.
    Note this guard is about headers set INSIDE Django — the host Caddy sits
    OUTSIDE and overwrites whatever we set at the edge (see module docstring), so
    on prod Caddy is the effective source of truth regardless of this guard.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response and "Content-Security-Policy-Report-Only" not in response:
            # Unfold /admin/ needs 'unsafe-eval' (Alpine's runtime new Function());
            # every other path keeps the strict policy.
            policy = CSP_POLICY_ADMIN if request.path.startswith("/admin") else CSP_POLICY
            response[CSP_HEADER_NAME] = policy
        return response
