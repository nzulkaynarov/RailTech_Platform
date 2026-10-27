"""Ответы ERP на «Создать заявку» (шов 0.8.0): 409 — постоянная ошибка, не временная (W16-D1-2)."""

import httpx
import pytest

from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp_requests import _result


def test_idempotency_conflict_is_a_permanent_conflict_with_a_reason() -> None:
    response = httpx.Response(409, json={"detail": "IDEMPOTENCY_CONFLICT"})
    with pytest.raises(ConflictError) as caught:
        _result(response)
    assert caught.value.details["reason"] == Reason.ERP_REQUEST_CONFLICT
    assert caught.value.details["erp_detail"] == "IDEMPOTENCY_CONFLICT"
    assert "другими данными" in caught.value.message


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (404, NotFoundError),
        (422, ValidationFailedError),
        (401, UpstreamUnavailableError),
        (503, UpstreamUnavailableError),
    ],
)
def test_other_statuses(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        _result(httpx.Response(status, json={"detail": "X"}))


def test_created_request() -> None:
    result = _result(
        httpx.Response(
            201, json={"erp_company_id": 1, "erp_request_id": 2, "number": "ЗВ-2026-001"}
        )
    )
    assert (result.erp_request_id, result.number) == (2, "ЗВ-2026-001")
