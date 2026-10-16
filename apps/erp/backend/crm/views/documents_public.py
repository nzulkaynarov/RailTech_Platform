"""Transitional re-export of public document views (M2-ERP-03).

Canonical home is now `portal.public_views`.
"""

from portal.public_views import (  # noqa: F401
    _UNAVAILABLE_COPY,
    PUBLIC_PDF_MAX_AUTO_RETRIES,
    PUBLIC_PDF_RETRY_AFTER_SECONDS,
    PublicDocumentView,
    _resolve_document,
    _unavailable,
)

__all__ = [
    "PUBLIC_PDF_RETRY_AFTER_SECONDS",
    "PUBLIC_PDF_MAX_AUTO_RETRIES",
    "_UNAVAILABLE_COPY",
    "_resolve_document",
    "_unavailable",
    "PublicDocumentView",
]
