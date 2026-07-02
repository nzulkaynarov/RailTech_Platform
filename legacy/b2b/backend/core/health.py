import logging
import time

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)

_cache = {"result": None, "ts": 0}
_TTL = 10  # seconds


def health_check(request):
    """
    Simple health check endpoint for Docker/K8s.
    Returns 200 if the service is up and database is responsive.
    Caches result for 10s to avoid hammering remote DB on every probe.
    """
    now = time.monotonic()
    if _cache["result"] and (now - _cache["ts"]) < _TTL:
        return _cache["result"]

    health_status = {
        "status": "unhealthy",
        "database": "down",
    }

    try:
        connection.ensure_connection()
        health_status["database"] = "up"
        health_status["status"] = "healthy"
        resp = JsonResponse(health_status, status=200)
    except Exception:
        # SEC-11: log the real DB error server-side, but never leak driver/host
        # internals to an unauthenticated health probe — a generic status only.
        logger.exception("Health check DB connection failed")
        resp = JsonResponse(health_status, status=503)

    _cache["result"] = resp
    _cache["ts"] = now
    return resp
