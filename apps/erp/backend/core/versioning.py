"""API deprecation / Sunset headers — Sprint D / F2.6.

RFC 8594: when an API version is scheduled for removal, its responses carry
`Deprecation: true` and `Sunset: <http-date|ISO-date>` so clients get machine-
readable advance notice instead of a surprise 404 on cutover.

Driven by settings.API_SUNSET = {"v1": "2027-01-01", ...}. The version is read from
the request path (/api/<version>/…) so it works at response time without depending on
DRF's per-view request.version. No-op while API_SUNSET is empty (current state).
"""

import re

from django.conf import settings

_API_VERSION_RE = re.compile(r"^/api/(v\d+)/")


class SunsetHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        sunset = getattr(settings, "API_SUNSET", None) or {}
        if sunset:
            match = _API_VERSION_RE.match(request.path)
            if match and match.group(1) in sunset:
                response["Deprecation"] = "true"
                response["Sunset"] = str(sunset[match.group(1)])
        return response
