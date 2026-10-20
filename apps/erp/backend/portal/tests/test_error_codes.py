"""Все `detail`, которые отдаёт портал, есть в `ErrorCode` контракта (FIX-21, Q-17).

Три слоя: (1) `portal.error_codes.ERROR_CODES` совпадает с перечнем в контракте; (2) разбор исходников `portal/` —
каждый код, который портал выбрасывает или возвращает в `{"detail": …}`, входит в перечень; (3) обработчик
исключений приводит чужие исключения (DRF, Django) к коду, а не к английской фразе.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from django.http import Http404
from portal.error_codes import ERROR_CODES, FALLBACK_BY_STATUS
from portal.exceptions import (
    PortalBadRequest,
    PortalConflict,
    PortalDeliveryFailed,
    PortalGone,
    portal_exception_handler,
)
from portal.tests.contract_support import error_codes
from rest_framework import exceptions

PORTAL_DIR = Path(__file__).resolve().parents[1]

#: Публичные страницы КП и документов (`/api/v1/public/…`) — не часть `erp-portal.yaml`, у них свои ответы.
NOT_PORTAL_API = {"public_views.py"}
#: Исключения и вызовы, первый аргумент которых — код `detail`.
CODE_CALLS = {
    "PortalConflict",
    "PortalGone",
    "PortalTooManyRequests",
    "PortalDeliveryFailed",
    "PortalValidationError",
    "PortalBadRequest",
    "PermissionDenied",
    "NotAuthenticated",
    "AuthenticationFailed",
    "ValidationError",
}
CODE_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")


def portal_sources():
    for path in sorted(PORTAL_DIR.rglob("*.py")):
        relative = path.relative_to(PORTAL_DIR)
        if "tests" in relative.parts or "migrations" in relative.parts:
            continue
        if path.name in NOT_PORTAL_API or path.name == "error_codes.py":
            continue
        yield relative, ast.parse(path.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _constant(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and CODE_SHAPE.match(node.value):
        return node.value
    return None


def emitted_codes() -> dict[str, set[str]]:
    """Код → где встречается. Берём: первый аргумент исключений, `{"detail": "CODE"}`, `message`/`default_detail`."""
    found: dict[str, set[str]] = {}

    def add(code, where):
        if code:
            found.setdefault(code, set()).add(str(where))

    for relative, tree in portal_sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in CODE_CALLS and node.args:
                add(_constant(node.args[0]), relative)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "detail":
                        add(_constant(value), relative)
            elif isinstance(node, ast.Assign):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if names & {"message", "default_detail"}:
                    add(_constant(node.value), relative)
            elif isinstance(node, ast.FunctionDef):
                for arg, default in zip(reversed(node.args.args), reversed(node.args.defaults)):
                    if arg.arg == "detail":
                        add(_constant(default), relative)
    return found


def test_error_code_list_is_the_contract_enum():
    assert list(ERROR_CODES) == error_codes(), "portal/error_codes.py разошёлся с ErrorCode в erp-portal.yaml"
    assert len(set(ERROR_CODES)) == len(ERROR_CODES)


def test_fallback_codes_are_known():
    assert set(FALLBACK_BY_STATUS.values()) <= set(ERROR_CODES)


def test_every_code_emitted_by_portal_sources_is_in_error_code():
    found = emitted_codes()
    # защита от пустого прохода: разбор действительно видит коды разных частей портала
    assert {"QUOTE_FINALIZED", "FILE_REQUIRED", "UNAUTHORIZED", "MAGIC_LINK_EXPIRED", "TOO_MANY_REQUESTS"} <= set(found)
    unknown = {code: sorted(where) for code, where in found.items() if code not in error_codes()}
    assert not unknown, f"портал отдаёт detail, которого нет в ErrorCode контракта: {unknown}"


def test_middleware_codes_are_known():
    middleware = (PORTAL_DIR / "middleware.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"detail": "([A-Z_]+)"', middleware)) <= set(error_codes())


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (exceptions.ParseError("JSON parse error - Expecting value"), 422, "VALIDATION_ERROR"),
        (exceptions.MethodNotAllowed("PATCH"), 405, "NOT_FOUND"),
        (exceptions.UnsupportedMediaType("text/plain"), 415, "UNSUPPORTED_MEDIA_TYPE"),
        (exceptions.NotAcceptable(), 406, "UNSUPPORTED_MEDIA_TYPE"),
        (exceptions.NotAuthenticated(), 401, "UNAUTHORIZED"),
        (exceptions.NotAuthenticated("UNAUTHORIZED"), 401, "UNAUTHORIZED"),
        (exceptions.AuthenticationFailed("INVALID_INIT_DATA"), 401, "INVALID_INIT_DATA"),
        (exceptions.PermissionDenied(), 403, "FORBIDDEN"),
        (exceptions.PermissionDenied("You do not have permission"), 403, "FORBIDDEN"),
        (exceptions.NotFound(), 404, "NOT_FOUND"),
        (Http404(), 404, "NOT_FOUND"),
        (exceptions.Throttled(wait=3), 429, "TOO_MANY_REQUESTS"),
        (exceptions.ValidationError({"reason": ["This field is required."]}), 422, "VALIDATION_ERROR"),
        (exceptions.ValidationError(["boom"]), 422, "VALIDATION_ERROR"),
        (
            exceptions.ValidationError({"reason": [exceptions.ErrorDetail("REASON_REQUIRED", code="required")]}),
            422,
            "REASON_REQUIRED",
        ),
        (PortalConflict("QUOTE_EXPIRED"), 409, "QUOTE_EXPIRED"),
        (PortalConflict(), 409, "CONFLICT"),
        (PortalGone(), 410, "MAGIC_LINK_EXPIRED"),
        (PortalDeliveryFailed(), 503, "DELIVERY_FAILED"),
        (PortalBadRequest("FILE_REQUIRED"), 400, "FILE_REQUIRED"),
    ],
)
def test_exception_handler_always_returns_a_known_code(exc, status, code):
    response = portal_exception_handler(exc, {})
    assert response.status_code == status
    assert response.data == {"detail": code}  # ровно один ключ: схема Error запрещает остальные
    assert code in error_codes()


# ── FIX-54 (хвост FIX-25): неизвестный путь под /api/portal/ — JSON 404 портала, а не HTML Django ────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/portal/v1/no-such-endpoint",
        "/api/portal/v1/auth/magic/some-token",
        "/api/portal/v2/quotes",
        "/api/portal/",
        "/api/portal/nothing/here/",
    ],
)
@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_unknown_portal_path_is_json_not_found(anon_portal_client, path, method):
    response = getattr(anon_portal_client, method)(path)
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"detail": "NOT_FOUND"}
