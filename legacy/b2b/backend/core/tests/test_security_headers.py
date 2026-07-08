"""
Security-hardening regression tests (added 2026-06-26).

Covers two prod gaps found by an external HTTP study of https://b2b.railtech.uz:
  1. OpenAPI schema (/api/schema/) was anonymously readable — it must now be
     gated behind IsAdminUser (401/403 for anon, 200 for staff).
  2. No Content-Security-Policy header — every response must now carry a CSP
     header (Content-Security-Policy or -Report-Only) from the middleware.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CustomUser


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestSchemaGating:
    """/api/schema/ must not be anonymously public (drf-spectacular leak)."""

    def test_anonymous_schema_is_denied(self, client):
        resp = client.get(reverse("schema"))
        assert resp.status_code in (401, 403), f"schema must be gated, got {resp.status_code}"

    def test_staff_can_read_schema(self, client):
        admin = CustomUser.objects.create_superuser(
            email="schema-admin@railtech.test",
            username="schema-admin@railtech.test",
            password="pw-Test1234!",
        )
        client.force_authenticate(user=admin)
        resp = client.get(reverse("schema"))
        assert resp.status_code == 200

    def test_non_staff_user_is_denied(self, client):
        user = CustomUser.objects.create_user(
            email="plain@railtech.test",
            username="plain@railtech.test",
            password="pw-Test1234!",
        )
        client.force_authenticate(user=user)
        resp = client.get(reverse("schema"))
        assert resp.status_code == 403


@pytest.mark.django_db
class TestCspHeader:
    """A Content-Security-Policy[-Report-Only] header must be present on responses."""

    def _csp(self, response):
        return response.get("Content-Security-Policy") or response.get("Content-Security-Policy-Report-Only")

    def test_csp_present_on_api_response(self, client):
        resp = client.get(reverse("health_check"))
        csp = self._csp(resp)
        assert csp is not None, "CSP header missing on API response"
        assert "default-src 'self'" in csp

    def test_csp_present_on_root_health(self, client):
        resp = client.get("/health/")
        assert self._csp(resp) is not None

    def test_admin_csp_allows_unsafe_eval(self, client):
        # Unfold /admin/ ships Alpine.js, which compiles x-* directives with
        # new Function() at runtime → the admin CSP must allow 'unsafe-eval'
        # (without it the login page renders dimmed + unclickable).
        resp = client.get("/admin/login/")
        csp = self._csp(resp)
        assert csp is not None
        assert "script-src 'self' 'unsafe-eval'" in csp, f"admin CSP must allow unsafe-eval, got: {csp}"

    def test_non_admin_csp_has_no_unsafe_eval(self, client):
        # The public SPA + /api keep the strict policy — a Vite build never evals,
        # so 'unsafe-eval' must NOT leak onto non-admin responses.
        resp = client.get("/health/")
        csp = self._csp(resp)
        assert csp is not None
        assert "'unsafe-eval'" not in csp, f"non-admin CSP must NOT allow unsafe-eval, got: {csp}"
