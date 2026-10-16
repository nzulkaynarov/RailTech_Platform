"""Transitional re-export of public quote views (M2-ERP-03).

Canonical home is now `portal.public_views`.
"""

from portal.public_views import (  # noqa: F401
    _UNAVAILABLE_COPY,
    PUBLIC_PDF_MAX_AUTO_RETRIES,
    PUBLIC_PDF_RETRY_AFTER_SECONDS,
    PublicQuoteAcceptView,
    PublicQuotePageScriptView,
    PublicQuoteRejectView,
    PublicQuoteRequestCodeView,
    PublicQuoteView,
    PublicQuoteViewedView,
    _client_ip,
    _gate_error,
    _mask_email,
    _newer_sent_version,
    _PublicQuoteBase,
    _resolve_quote,
    _unavailable,
)

__all__ = [
    "PUBLIC_PDF_RETRY_AFTER_SECONDS",
    "PUBLIC_PDF_MAX_AUTO_RETRIES",
    "_UNAVAILABLE_COPY",
    "_resolve_quote",
    "_gate_error",
    "_client_ip",
    "_mask_email",
    "_unavailable",
    "_PublicQuoteBase",
    "_newer_sent_version",
    "PublicQuotePageScriptView",
    "PublicQuoteView",
    "PublicQuoteViewedView",
    "PublicQuoteRequestCodeView",
    "PublicQuoteAcceptView",
    "PublicQuoteRejectView",
]
