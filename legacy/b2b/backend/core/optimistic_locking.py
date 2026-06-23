"""Optimistic concurrency control for DRF ViewSets — Sprint D / F2.5.

HTTP conditional updates (RFC 7232): a single-object read returns a weak `ETag`
derived from the row's `updated_at`; an update may carry `If-Match: <etag>` and is
rejected **412 Precondition Failed** if the row changed since the client read it —
so two people editing the same Quote/Contract/Invoice can't silently clobber each
other's save (lost update).

`select_for_update` (used in the service layer) serializes writes WITHIN one
transaction; it does NOT stop a stale read-modify-write across two separate HTTP
requests. That gap is exactly what this closes.

Opt-in: no `If-Match` header → normal behaviour, so it can be rolled out before the
frontend starts sending the header. `Quote.version` is a revision counter, not a
concurrency token — this is the real token.
"""

import hashlib

from rest_framework import status
from rest_framework.response import Response


class OptimisticLockingMixin:
    """Mix in BEFORE the ViewSet base. Requires the model to have `updated_at`."""

    def _etag_for(self, obj) -> str:
        ts = getattr(obj, "updated_at", None)
        raw = f"{obj.pk}:{ts.isoformat() if ts else ''}"
        return 'W/"' + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] + '"'

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        response = Response(self.get_serializer(instance).data)
        response["ETag"] = self._etag_for(instance)
        return response

    def update(self, request, *args, **kwargs):
        # DRF routes partial_update → update(partial=True), so this covers PATCH too.
        if_match = request.headers.get("If-Match")
        if if_match:
            current = self._etag_for(self.get_object())
            if if_match != current:
                return Response(
                    {"detail": "PRECONDITION_FAILED_STALE_WRITE"},
                    status=status.HTTP_412_PRECONDITION_FAILED,
                )
        response = super().update(request, *args, **kwargs)
        # Refresh the ETag on the response so the client holds the new token.
        if response.status_code < 300:
            response["ETag"] = self._etag_for(self.get_object())
        return response
