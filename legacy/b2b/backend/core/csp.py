"""
Content-Security-Policy middleware for the Django app (API + Unfold /admin/).

Why a custom middleware instead of django-csp:
    django-csp is not (and need not be) a dependency — our policy is small and
    differs only between the Unfold admin HTML and the JSON API, which a ~30-line
    middleware expresses more clearly than the per-view nonce machinery django-csp
    pulls in. If the policy ever grows nonces/per-view overrides, switch to
    django-csp then.

Where CSP actually matters in this deployment:
    The public-facing surface that renders HTML to a browser is the React SPA,
    served by the **host Caddy** on the VPS (deploy/caddy/b2b.railtech.uz.caddy) —
    NOT Django. Django serves the JSON API and the Unfold /admin/ HTML. So:
      * This middleware protects the /admin/ HTML (and stamps a header on every
        API response, harmless for JSON).
      * The SPA's CSP MUST be mirrored on the host Caddy — see the comment block
        added to deploy/caddy/b2b.railtech.uz.caddy.

Posture (conservative first rollout):
    Defaults to **Content-Security-Policy-Report-Only** so a missed Unfold asset
    can only produce a console warning, never a broken admin page. Flip to the
    enforcing header by setting env CSP_REPORT_ONLY=false once the report-only run
    confirms Unfold loads cleanly. The policy itself is identical in both modes.

Policy rationale:
    Unfold/Django admin emits inline <style>/<script> and inline event handlers,
    so style-src and script-src need 'unsafe-inline'. It also uses data: images
    and (Trix editor) blob: workers. The API path gets the same self-only policy;
    JSON responses don't execute it, so it's a no-op there but documents intent.
"""

import os

# Single source of truth for the policy string. Kept self-only with the minimal
# 'unsafe-inline' the legacy Django/Unfold admin requires; no third-party origins.
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
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

# Report-Only by default — non-breaking first rollout. Set CSP_REPORT_ONLY=false
# in prod env once Unfold /admin/ is confirmed clean to switch to enforcing.
_REPORT_ONLY = os.environ.get("CSP_REPORT_ONLY", "true").strip().lower() != "false"
CSP_HEADER_NAME = "Content-Security-Policy-Report-Only" if _REPORT_ONLY else "Content-Security-Policy"


class ContentSecurityPolicyMiddleware:
    """Stamp a Content-Security-Policy[-Report-Only] header on every response.

    Does not overwrite a CSP header already set upstream (e.g. by a fronting
    proxy), so the host Caddy / nginx remains the source of truth if it sets one.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response and "Content-Security-Policy-Report-Only" not in response:
            response[CSP_HEADER_NAME] = CSP_POLICY
        return response
