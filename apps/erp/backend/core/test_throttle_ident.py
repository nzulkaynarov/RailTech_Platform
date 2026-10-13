"""SEC-04 — throttle identity integrity: NUM_PROXIES makes X-Forwarded-For unforgeable.

DRF's BaseThrottle.get_ident() keys the per-IP throttles (login, register,
password-reset, lead-submit). Without NUM_PROXIES every forged X-Forwarded-For
value becomes a fresh throttle bucket — a full bypass of the only brute-force
defence. With NUM_PROXIES=0 (dev: no proxy) XFF is ignored entirely; with
NUM_PROXIES=1 (prod: host Caddy overwrites XFF with the client IP) the ident is
the LAST — trusted — XFF entry. No DB needed; tests get_ident() directly.
"""

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.test.client import RequestFactory
from rest_framework.throttling import BaseThrottle

REMOTE = "172.18.0.1"  # the TCP peer Django actually sees (e.g. docker bridge)


class ThrottleIdentTest(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.throttle = BaseThrottle()

    def _ident(self, xff=None):
        meta = {"REMOTE_ADDR": REMOTE}
        if xff is not None:
            meta["HTTP_X_FORWARDED_FOR"] = xff
        return self.throttle.get_ident(self.rf.post("/api/v1/auth/token/", **meta))

    @override_settings(REST_FRAMEWORK={})
    def test_drf_default_none_is_forgeable_hence_the_explicit_pin(self):
        # Documents the hole the explicit setting closes: with DRF's default
        # (NUM_PROXIES=None) every forged XFF value is a distinct throttle bucket.
        idents = {self._ident(xff=f"10.99.0.{i}") for i in range(1, 11)}
        self.assertEqual(len(idents), 10)

    @override_settings(REST_FRAMEWORK={"NUM_PROXIES": 0})
    def test_num_proxies_0_ignores_forged_xff(self):
        # Dev topology: clients hit Daphne directly — XFF is attacker-controlled.
        idents = {self._ident(xff=f"10.99.0.{i}") for i in range(1, 11)}
        self.assertEqual(idents, {REMOTE})  # one bucket, not ten

    @override_settings(REST_FRAMEWORK={"NUM_PROXIES": 0})
    def test_num_proxies_0_uses_remote_addr_without_xff(self):
        self.assertEqual(self._ident(), REMOTE)

    @override_settings(REST_FRAMEWORK={"NUM_PROXIES": 1})
    def test_num_proxies_1_keys_on_last_trusted_xff_entry(self):
        # Prod topology: the single trusted proxy (Caddy) writes the client IP as
        # the LAST XFF entry. Rotating forged prefixes must map to ONE bucket.
        idents = {self._ident(xff=f"6.6.6.{i}, 203.0.113.7") for i in range(1, 11)}
        self.assertEqual(idents, {"203.0.113.7"})

    @override_settings(REST_FRAMEWORK={"NUM_PROXIES": 1})
    def test_num_proxies_1_falls_back_to_remote_addr_without_xff(self):
        # Docker healthchecks / loopback calls send no XFF at all.
        self.assertEqual(self._ident(), REMOTE)

    def test_project_settings_pin_num_proxies(self):
        # Regression guard: settings must define NUM_PROXIES explicitly (DRF's
        # default None keys the throttle on the ENTIRE forgeable XFF header).
        self.assertIn("NUM_PROXIES", settings.REST_FRAMEWORK)
        num_proxies = settings.REST_FRAMEWORK["NUM_PROXIES"]
        self.assertIsInstance(num_proxies, int)
        self.assertGreaterEqual(num_proxies, 0)
