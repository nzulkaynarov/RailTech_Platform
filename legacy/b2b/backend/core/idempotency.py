"""HTTP Idempotency-Key middleware (Stripe-style) — Sprint D / F2.4.

A client sends `Idempotency-Key: <opaque>` on a mutating request (POST/PUT/PATCH).
The first request executes and its response is cached; a retry carrying the same
key replays the cached response instead of re-executing — so a double-click, a
client/proxy retry, or a flaky connection can't create duplicate contracts /
invoices / payments.

Design notes:
- **Opt-in per request.** No header → pass straight through, unchanged behaviour.
- **Scoped to the caller.** The cache namespace includes a hash of the Authorization
  header (the JWT isn't resolved to request.user this early in the stack), so a key
  is private to its bearer and can't collide or be replayed across accounts.
- **Bound to method+path.** Reusing one key on a different endpoint is a client bug,
  not a replay — those get separate namespaces.
- **Concurrency-safe.** A second request with the same key while the first is still
  in flight gets 409 (in progress) rather than double-executing.
- **Only final responses are cached** (status < 500, not the 409). 5xx stays
  retryable. This layer complements — does not replace — the domain-level guards
  (e.g. record_payment dedupes by bank reference).
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.template.response import ContentNotRenderedError

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH"}


class IdempotencyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ttl = int(getattr(settings, "IDEMPOTENCY_TTL_SECONDS", 24 * 3600))
        self.lock_ttl = int(getattr(settings, "IDEMPOTENCY_LOCK_SECONDS", 90))

    def __call__(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key or request.method not in _MUTATING:
            return self.get_response(request)

        ns = self._namespace(request, key)
        result_key = f"{ns}:result"
        lock_key = f"{ns}:lock"

        cached = cache.get(result_key)
        if cached is not None:
            return self._replay(cached)

        # Atomically claim the in-flight slot — add() is a no-op (returns False) if
        # the key already exists, so only the first concurrent request proceeds.
        if not cache.add(lock_key, "1", timeout=self.lock_ttl):
            # Re-check the result: the holder may have just finished (avoid a false 409).
            cached = cache.get(result_key)
            if cached is not None:
                return self._replay(cached)
            return JsonResponse({"detail": "IDEMPOTENCY_KEY_IN_PROGRESS"}, status=409)

        try:
            response = self.get_response(request)
        except Exception:  # noqa: BLE001 — fault barrier: any view crash must release the lock, then re-raise
            # View blew up — release the slot so the client can retry, then re-raise.
            cache.delete(lock_key)
            raise

        if response.status_code < 500 and response.status_code != 409:
            stored = self._serialize(response)
            if stored is not None:
                cache.set(result_key, stored, timeout=self.ttl)
        cache.delete(lock_key)
        return response

    @staticmethod
    def _namespace(request, key: str) -> str:
        auth = request.headers.get("Authorization", "")
        caller = hashlib.sha256(auth.encode("utf-8")).hexdigest()[:16] if auth else "anon"
        return f"idem:{caller}:{request.method}:{request.path}:{key}"

    @staticmethod
    def _serialize(response):
        try:
            content = response.content
        except ContentNotRenderedError:
            return None  # streaming/file response — don't cache
        return {
            "status": response.status_code,
            "content": content,
            "content_type": response.get("Content-Type", "application/json"),
        }

    @staticmethod
    def _replay(cached):
        resp = HttpResponse(
            cached["content"],
            status=cached["status"],
            content_type=cached["content_type"],
        )
        resp["Idempotent-Replay"] = "true"
        return resp
