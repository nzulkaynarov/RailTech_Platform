"""F2.4 — Idempotency-Key middleware. No DB needed; uses a local-memory cache."""

from django.core.cache import cache
from django.http import JsonResponse
from django.test import SimpleTestCase, override_settings
from django.test.client import RequestFactory

from core.idempotency import IdempotencyMiddleware

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "idem-test"}}


@override_settings(CACHES=LOCMEM)
class IdempotencyMiddlewareTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()

    def _req(self, key="K1", method="post", auth="Bearer t1"):
        headers = {}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        if auth:
            headers["HTTP_AUTHORIZATION"] = auth
        return getattr(self.rf, method)("/api/v1/crm/contracts/generate-from-quote/", **headers)

    def _mw(self, body=None, status=201):
        calls = {"n": 0}

        def inner(request):
            calls["n"] += 1
            return JsonResponse(body or {"id": calls["n"]}, status=status)

        return IdempotencyMiddleware(inner), calls

    def test_no_key_passes_through_every_time(self):
        mw, calls = self._mw()
        mw(self._req(key=None))
        mw(self._req(key=None))
        self.assertEqual(calls["n"], 2)  # not deduped without a key

    def test_get_with_key_is_ignored(self):
        mw, calls = self._mw()
        mw(self._req(method="get"))
        mw(self._req(method="get"))
        self.assertEqual(calls["n"], 2)  # only mutating methods are guarded

    def test_same_key_replays_response(self):
        mw, calls = self._mw(body={"id": 42}, status=201)
        first = mw(self._req())
        second = mw(self._req())
        self.assertEqual(calls["n"], 1)  # view executed once
        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(first.content, second.content)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_different_key_executes_again(self):
        mw, calls = self._mw()
        mw(self._req(key="A"))
        mw(self._req(key="B"))
        self.assertEqual(calls["n"], 2)

    def test_same_key_different_caller_is_isolated(self):
        mw, calls = self._mw()
        mw(self._req(key="K", auth="Bearer userA"))
        mw(self._req(key="K", auth="Bearer userB"))
        self.assertEqual(calls["n"], 2)  # namespaced by Authorization hash

    def test_concurrent_retry_gets_409(self):
        holder = {}

        def inner(request):
            # A concurrent retry with the same key arrives mid-flight → must 409.
            resp = holder["mw"](self._req())
            holder["concurrent_status"] = resp.status_code
            return JsonResponse({"ok": True}, status=201)

        mw = IdempotencyMiddleware(inner)
        holder["mw"] = mw
        first = mw(self._req())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(holder["concurrent_status"], 409)

    def test_server_error_not_cached(self):
        mw, calls = self._mw(status=500)
        mw(self._req())
        mw(self._req())
        self.assertEqual(calls["n"], 2)  # 5xx stays retryable
