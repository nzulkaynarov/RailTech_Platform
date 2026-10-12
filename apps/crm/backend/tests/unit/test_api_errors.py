"""Формат ошибок API: `{code, message, details}` с подкодом `details.reason` и `details.field`."""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api import errors
from app.domain import errors as e
from app.domain.uploads import check_file_size


class Body(BaseModel):
    email: str = Field(min_length=3)
    age: int


def _app(raised: dict[str, Exception]) -> FastAPI:
    app = FastAPI()
    errors.install(app)

    @app.get("/raise/{name}")
    async def boom(name: str) -> None:
        raise raised[name]

    @app.post("/form")
    async def form(body: Body) -> dict[str, str]:
        return {"ok": body.email}

    return app


CASES: dict[str, tuple[Exception, int, dict[str, Any]]] = {
    "email": (
        e.ConflictError("email already registered", reason=e.Reason.EMAIL_TAKEN, field="email"),
        409,
        {"code": "conflict", "details": {"reason": "email_taken", "field": "email"}},
    ),
    "taken": (
        e.ConflictError(
            "lead is already taken",
            reason=e.Reason.LEAD_TAKEN,
            assigned_user_id=7,
            assigned_user_name="Дилшод",
        ),
        409,
        {
            "code": "conflict",
            "details": {
                "reason": "lead_taken",
                "assigned_user_id": 7,
                "assigned_user_name": "Дилшод",
            },
        },
    ),
    "password": (
        e.ValidationFailedError(
            "current password is wrong", reason=e.Reason.WRONG_PASSWORD, field="current_password"
        ),
        422,
        {
            "code": "validation_failed",
            "details": {"reason": "wrong_password", "field": "current_password"},
        },
    ),
    "plain": (e.NotFoundError("lead not found"), 404, {"code": "not_found", "details": {}}),
    "http404": (HTTPException(404, "lead not found"), 404, {"code": "not_found", "details": {}}),
    "http400": (HTTPException(400), 400, {"code": "http_error", "details": {}}),
}


@pytest.mark.parametrize("name", list(CASES))
def test_error_body_format(name: str) -> None:
    _, status, expected = CASES[name]
    response = TestClient(_app({k: v[0] for k, v in CASES.items()})).get(f"/raise/{name}")
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"code", "message", "details"}
    assert payload["code"] == expected["code"]
    assert payload["details"] == expected["details"]
    assert payload["message"]


def test_unknown_route_is_not_found_in_the_same_format() -> None:
    response = TestClient(_app({})).get("/nope")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Not Found", "details": {}}


def test_request_validation_names_the_field() -> None:
    response = TestClient(_app({})).post("/form", json={"email": "x", "age": 3})
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "validation_failed"
    assert payload["details"]["field"] == "email"
    assert payload["details"]["errors"][0]["field"] == "email"


def test_request_validation_without_body_has_no_field() -> None:
    response = TestClient(_app({})).post("/form")
    assert response.status_code == 422
    assert "field" not in response.json()["details"]


@pytest.mark.parametrize(
    ("loc", "field"),
    [
        (("body", "email"), "email"),
        (("query", "limit"), "limit"),
        (("body", "items", 0, "name"), "items"),
        (("body",), None),
    ],
)
def test_field_of(loc: tuple[int | str, ...], field: str | None) -> None:
    assert errors.field_of(loc) == field


@pytest.mark.parametrize(
    ("size", "reason"),
    [(0, "file_empty"), (26 * 1024 * 1024, "file_too_large")],
)
def test_file_size_reasons(size: int, reason: str) -> None:
    with pytest.raises(e.ValidationFailedError) as caught:
        check_file_size(size, 25 * 1024 * 1024)
    assert caught.value.details["reason"] == reason
    assert caught.value.details["field"] == "file"


def test_file_within_limit_passes() -> None:
    check_file_size(1, 25 * 1024 * 1024)


def test_reason_values_are_a_stable_contract() -> None:
    """Фронт показывает текст по `details.reason`: переименование — ломающее изменение."""
    assert {r.value for r in e.Reason} == {
        "email_taken",
        "setup_done",
        "setup_code_invalid",
        "setup_code_expired",
        "setup_locked",
        "invalid_email",
        "invalid_phone",
        "telegram_taken",
        "telegram_linked_elsewhere",
        "telegram_unknown",
        "telegram_not_linked",
        "telegram_refused",
        "bot_not_configured",
        "wrong_password",
        "same_password",
        "weak_password",
        "inactive_colleague",
        "lead_taken",
        "take_first",
        "deal_not_closed",
        "not_lead_owner",
        "already_with_bot",
        "no_open_handoff",
        "snooze_range",
        "service_request_closed",
        "file_too_large",
        "file_empty",
        "file_type",
        "document_indexing",
        "invalid_bot_token",
        "telegram_unavailable",
        "secrets_key_missing",
        "bot_not_running",
        "channel_not_configured",
        "channel_send_failed",
        "assist_disabled",
        "assist_budget",
        "assist_unavailable",
        "assist_empty",
        "assist_no_history",
        "deal_won_final",
        "no_consent",
        "litellm_unavailable",
        "model_key_required",
        "model_in_config",
    }
