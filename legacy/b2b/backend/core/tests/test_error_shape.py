"""ARCH-05 repo hygiene: hand-written HTTP error bodies use the DRF-native shape.

Every hand-written error Response in the view layer must be ``{"detail": CODE}`` —
the same shape DRF's own exception handler emits — never ``{"error": CODE}``.
The frontend (``lib/apiError.ts``) reads ``detail`` as the canonical key.

Intentionally OUT of scope (different, non-HTTP contracts):
- Celery task RESULT payloads (``sourcing/tasks_ai.py`` returns ``{"error": CODE}`` —
  the aiJob result contract the SPA reads via ``result.error``; ``sourcing/tasks.py``,
  ``crm/tasks.py`` likewise return result dicts, not HTTP responses),
- WebSocket message payloads (``crm/consumers.py``),
- service-layer ``(obj, error_code)`` return tuples and per-item report fields
  inside 200 success bodies (e.g. ``bulk_verify_kyc``'s ``skipped[].error``).

The scan therefore covers only view-layer modules — the files that build HTTP
Response objects — and is a plain source grep so it stays green regardless of
how black (120 cols) wraps the call.
"""

import pathlib
import re

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]

# Django apps whose view layer is scanned.
APPS = ("accounts", "catalog", "core", "crm", "master_data", "notifications", "sourcing")

# Non-"views*" modules that also hand-build HTTP Response objects.
EXTRA_HTTP_MODULES = frozenset(
    {
        "sourcing/ai_jobs.py",
        "core/health.py",
        "core/idempotency.py",
    }
)

# Files allowed to keep an {"error": ...} literal (justified, documented exceptions).
# Keep EMPTY unless a frozen external contract requires the legacy key.
ALLOWLIST: frozenset = frozenset()

# An "error" key opening a dict literal or following another pair: {"error": / , "error":
# (single- or double-quoted). Does NOT match "error_count", "errors", etc.
ERROR_KEY_PATTERN = re.compile(r"""[{,]\s*(?:"error"|'error')\s*:""")


def _iter_view_layer_files():
    """Yield backend-relative paths of production view-layer modules."""
    for app in APPS:
        for path in sorted((BACKEND_DIR / app).rglob("*.py")):
            rel = path.relative_to(BACKEND_DIR)
            parts = rel.parts
            if "migrations" in parts or "tests" in parts or rel.name.startswith("test_"):
                continue
            in_views_package = "views" in parts[:-1] or "admin_api" in parts[:-1]
            is_views_module = rel.name.startswith("views")
            if in_views_package or is_views_module or str(rel) in EXTRA_HTTP_MODULES:
                yield rel


def test_no_error_key_in_view_layer_responses():
    """No production view module may build a ``{"error": ...}`` body (ARCH-05)."""
    offenders = []
    scanned = 0
    for rel in _iter_view_layer_files():
        if str(rel) in ALLOWLIST:
            continue
        scanned += 1
        source = (BACKEND_DIR / rel).read_text(encoding="utf-8")
        for match in ERROR_KEY_PATTERN.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{line_number}")
    # Guard the guard: an empty scan list would mean the layout changed and the test
    # silently stopped covering anything.
    assert scanned >= 10, f"View-layer scan looks broken — only {scanned} files found"
    assert not offenders, (
        "Hand-written HTTP error bodies must be {'detail': CODE} (ARCH-05), "
        "found legacy {'error': ...} literals in view-layer files:\n  " + "\n  ".join(offenders)
    )
