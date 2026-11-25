"""Ответы ERP на «Партнёр» из карточки лида (ЛП-1, шов 0.10.0): временные и постоянные ошибки."""

import httpx
import pytest

from app.domain.errors import Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.erp import ErpRateLimitedError
from app.integrations.erp_partner import (
    PartnerApplicationPayload,
    _result,
    partner_idempotency_key,
)


def test_created_and_repeated_application() -> None:
    created = _result(
        httpx.Response(201, json={"erp_application_id": 7, "status": "submitted", "created": True})
    )
    again = _result(
        httpx.Response(200, json={"erp_application_id": 7, "status": "submitted", "created": False})
    )
    assert (created.erp_application_id, created.created) == (7, True)
    assert (again.erp_application_id, again.created) == (7, False)


@pytest.mark.parametrize("status", [401, 403])
def test_token_refusal_is_temporary_and_named(status: int) -> None:
    with pytest.raises(UpstreamUnavailableError) as caught:
        _result(httpx.Response(status, json={"detail": "UNAUTHORIZED"}))
    assert caught.value.details["reason"] == Reason.ERP_UNAUTHORIZED


def test_rate_limit_is_a_pause_with_retry_after() -> None:
    with pytest.raises(ErpRateLimitedError):
        _result(httpx.Response(429, headers={"Retry-After": "7"}, json={"detail": "TOO_MANY"}))


@pytest.mark.parametrize("status", [409, 422])
def test_rejected_application_is_permanent(status: int) -> None:
    with pytest.raises(ValidationFailedError) as caught:
        _result(httpx.Response(status, json={"detail": "VALIDATION_ERROR"}))
    assert caught.value.details["reason"] == Reason.ERP_BAD_RESPONSE


@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, text="not json")])
def test_unavailable_or_broken_answer_is_temporary(response: httpx.Response) -> None:
    with pytest.raises(UpstreamUnavailableError):
        _result(response)


def test_idempotency_key_follows_lead_and_content() -> None:
    def payload(**changes: object) -> PartnerApplicationPayload:
        data: dict[str, object] = {
            "crm_lead_id": 5,
            "lead_number": "L-0005",
            "company_name": "A",
            "categories_description": "x",
            "contact_name": "B",
            "email": "a@b.example",
        }
        data.update(changes)
        return PartnerApplicationPayload(**data)  # type: ignore[arg-type]

    assert partner_idempotency_key(payload()) == partner_idempotency_key(payload())
    # a corrected form after a failure must not hit IDEMPOTENCY_CONFLICT
    assert partner_idempotency_key(payload()) != partner_idempotency_key(payload(company_name="C"))
    assert partner_idempotency_key(payload()) != partner_idempotency_key(payload(crm_lead_id=6))
