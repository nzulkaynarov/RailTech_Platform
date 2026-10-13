"""F2.6 — SunsetHeaderMiddleware (RFC 8594 deprecation headers). No DB."""

from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from django.test.client import RequestFactory

from core.versioning import SunsetHeaderMiddleware


class SunsetHeaderMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.mw = SunsetHeaderMiddleware(lambda request: HttpResponse("ok"))

    @override_settings(API_SUNSET={})
    def test_no_sunset_configured_no_headers(self):
        resp = self.mw(self.rf.get("/api/v1/crm/deals/"))
        self.assertNotIn("Deprecation", resp)
        self.assertNotIn("Sunset", resp)

    @override_settings(API_SUNSET={"v1": "2027-01-01"})
    def test_deprecated_version_gets_headers(self):
        resp = self.mw(self.rf.get("/api/v1/crm/deals/"))
        self.assertEqual(resp["Deprecation"], "true")
        self.assertEqual(resp["Sunset"], "2027-01-01")

    @override_settings(API_SUNSET={"v2": "2028-01-01"})
    def test_other_version_deprecated_does_not_tag_v1(self):
        resp = self.mw(self.rf.get("/api/v1/crm/deals/"))
        self.assertNotIn("Deprecation", resp)

    @override_settings(API_SUNSET={"v1": "2027-01-01"})
    def test_non_api_path_untouched(self):
        resp = self.mw(self.rf.get("/admin/"))
        self.assertNotIn("Deprecation", resp)
