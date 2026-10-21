"""FIX-55 / D-14: токены публичных ссылок на документы не попадают в журнал (как токен magic-link, FIX-15).

`django.request` и access-логи пишут путь запроса целиком; у публичных КП, документов и подписанных ссылок CRM токен
лежит в пути (`/public/quotes/<токен>/…`, `/public/documents/<токен>/`, `/public/doc-links/<токен>/`).
"""

import logging

import pytest

from core.logging import RedactPortalTokenFilter

TOKEN = "sEcReT_tok-1.abc~def"


def _redact(path):
    record = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "%s: %s", ("Gone", path), None)
    assert RedactPortalTokenFilter().filter(record) is True
    return record.getMessage()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"/api/v1/public/quotes/{TOKEN}/", "/api/v1/public/quotes/[REDACTED]/"),
        (f"/api/v1/public/quotes/{TOKEN}/accept/", "/api/v1/public/quotes/[REDACTED]/accept/"),
        (f"/api/v1/public/quotes/{TOKEN}/request-code/", "/api/v1/public/quotes/[REDACTED]/request-code/"),
        (f"/api/v1/public/quotes/{TOKEN}/viewed/", "/api/v1/public/quotes/[REDACTED]/viewed/"),
        (f"/api/v1/public/quotes/{TOKEN}/reject/", "/api/v1/public/quotes/[REDACTED]/reject/"),
        (f"/api/v1/public/documents/{TOKEN}/?export=pdf", "/api/v1/public/documents/[REDACTED]/?export=pdf"),
        (f"/api/v1/public/doc-links/{TOKEN}/", "/api/v1/public/doc-links/[REDACTED]/"),
        (f"/api/portal/v1/auth/magic/{TOKEN}", "/api/portal/v1/auth/magic/[REDACTED]"),
    ],
)
def test_public_document_tokens_are_redacted(path, expected):
    message = _redact(path)
    assert message == f"Gone: {expected}"
    assert TOKEN not in message


def test_paths_without_a_token_are_left_alone():
    assert _redact("/api/v1/public/quote-page.js") == "Gone: /api/v1/public/quote-page.js"
    assert _redact("/api/v1/quotes/12/") == "Gone: /api/v1/quotes/12/"


def test_token_in_a_full_access_log_line_is_redacted():
    record = logging.LogRecord(
        "core.access", logging.INFO, __file__, 1, "GET /api/v1/public/documents/%s/ 200 12ms", (TOKEN,), None
    )
    RedactPortalTokenFilter().filter(record)
    assert TOKEN not in record.getMessage()
