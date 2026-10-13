"""Sentry PII scrubber (before_send hook).

``sentry_sdk.init`` already sets ``send_default_pii=False``, but that only stops
Sentry's *own* auto-attached PII (cookies, request bodies it collects). It does
NOT scrub domain PII we ourselves put into an event — e.g. an ИНН / phone in a
request body echoed into ``request.data``, a serializer payload stashed in
``extra``, or a value logged as a breadcrumb.

This module masks that domain PII before the event leaves the process:
  * dict keys whose name hints at a secret/identifier (inn, phone, passport, bank,
    iban, card, account, token, password, secret) → value replaced wholesale;
  * free-text values that LOOK like an ИНН (9 or 12 digits) or a phone number →
    the matching span masked.

Only the containers we populate are walked (``request.data``, ``extra``,
breadcrumb ``data``) — never the exception message/stacktrace, so debuggability is
preserved. The hook is defensively total: any failure returns the event unchanged
rather than dropping the report.
"""

import re

MASK = "[Filtered]"

# Substrings that mark a dict KEY as sensitive (case-insensitive). Match on the whole
# value for these — the key name alone is enough signal (e.g. "bank_account": "...").
SENSITIVE_KEY_TOKENS = (
    "inn",
    "phone",
    "passport",
    "bank",
    "iban",
    "card",
    "account",
    "token",
    "password",
    "secret",
)

# ИНН: a standalone 9-digit (legal entity) or 12-digit (individual) run.
_INN_RE = re.compile(r"(?<!\d)(?:\d{9}|\d{12})(?!\d)")
# Phone-like: optional +, then a digit and 8+ more digits possibly spaced/dashed/(). Anchored
# so it does not swallow ordinary short numbers; applied AFTER the ИНН pass.
_PHONE_RE = re.compile(r"(?<![\d\w])\+?\d[\d\s()\-]{7,}\d(?![\d\w])")


def _is_sensitive_key(key) -> bool:
    lowered = str(key).lower()
    return any(token in lowered for token in SENSITIVE_KEY_TOKENS)


def _scrub_text(value: str) -> str:
    masked = _INN_RE.sub(MASK, value)
    masked = _PHONE_RE.sub(MASK, masked)
    return masked


def _scrub(node):
    """Recursively mask sensitive keys/values in a nested dict/list/str structure."""
    if isinstance(node, dict):
        return {key: (MASK if _is_sensitive_key(key) else _scrub(value)) for key, value in node.items()}
    if isinstance(node, (list, tuple)):
        return [_scrub(item) for item in node]
    if isinstance(node, str):
        return _scrub_text(node)
    return node


def _scrub_breadcrumbs(breadcrumbs) -> None:
    """Breadcrumbs arrive either as {"values": [...]} or a bare list; each crumb may
    carry a ``data`` dict. Scrub that data in place."""
    crumbs = breadcrumbs.get("values", []) if isinstance(breadcrumbs, dict) else breadcrumbs
    if not isinstance(crumbs, (list, tuple)):
        return
    for crumb in crumbs:
        if isinstance(crumb, dict) and isinstance(crumb.get("data"), (dict, list)):
            crumb["data"] = _scrub(crumb["data"])


def scrub_event(event, hint=None):
    """Sentry ``before_send`` hook — mask domain PII in the event we populate.

    Returns the (mutated) event, or the original event on any error. Never returns
    None (that would silently drop the report)."""
    try:
        request = event.get("request")
        if isinstance(request, dict) and "data" in request:
            request["data"] = _scrub(request["data"])
        if "extra" in event:
            event["extra"] = _scrub(event.get("extra"))
        if "breadcrumbs" in event:
            _scrub_breadcrumbs(event.get("breadcrumbs"))
    except Exception:  # noqa: BLE001 — scrubbing must never break error reporting
        return event
    return event
