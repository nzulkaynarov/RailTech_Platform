"""РЕЗ-1: канал заявки и номер входящего письма доходят до ERP в теле и в схеме формы."""

import uuid

import pytest
from pydantic import ValidationError

from app.integrations.erp_requests import ClientRequestPayload, payload_to_dict
from app.schemas.client_requests import RequestContactIn, RequestCreate


def _payload(**changes) -> ClientRequestPayload:
    base = {
        "crm_client_id": 1,
        "crm_request_id": 2,
        "summary": "s",
        "owner_crm_user_id": 3,
        "owner_name": "М",
    }
    base.update(changes)
    return ClientRequestPayload(**base)


def test_the_erp_body_carries_the_channel_and_the_registered_letter() -> None:
    body = payload_to_dict(_payload(initiated_by="staff", letter_number="ВХ-12/26"))
    assert (body["initiated_by"], body["letter_number"]) == ("staff", "ВХ-12/26")


def test_without_a_channel_the_request_is_the_clients_own() -> None:
    body = payload_to_dict(_payload())
    assert (body["initiated_by"], body["letter_number"]) == ("client", None)


def test_the_form_accepts_only_known_channels() -> None:
    fields = {
        "request_key": uuid.uuid4(),
        "contact": RequestContactIn(full_name="Иван", phone="+998901234567"),
        "summary": "s",
        "letter_file_id": uuid.uuid4(),
    }
    assert RequestCreate(**fields).initiated_by == "client"
    assert (
        RequestCreate(**fields, initiated_by="staff", letter_number="ВХ-1/26").letter_number
        == "ВХ-1/26"
    )
    with pytest.raises(ValidationError):
        RequestCreate(**fields, initiated_by="robot")
