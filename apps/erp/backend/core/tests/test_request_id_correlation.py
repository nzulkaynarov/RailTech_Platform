"""Хвост S0-6 и B3: `X-Request-ID` ERP — безопасная строка до 128 знаков, иначе новый UUID; этот ID — `correlationid` rt_bus.

Правило то же, что в CRM (`apps/crm/backend/app/log.py: is_valid_request_id`): Caddy пропускает клиентский заголовок как
есть, значение попадает в журналы и в конверт события, поэтому пробелы, переводы строк, чужие символы и длина больше 128
отвергаются. Цепочка: заголовок запроса → контекст rt_bus → `correlationid` события, опубликованного в этом запросе →
`X-Request-ID` доставки подписчику.
"""

import re
import uuid

import pytest
from django.db import transaction
from django.http import HttpResponse
from integration.models import CrmClientMapping
from integration.services import events
from integration.tests import bus_support
from integration.tests.world import make_company
from rt_bus import get_correlation_id, get_traceparent

from core.logging import RequestIDMiddleware, is_valid_request_id

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


@pytest.mark.parametrize(
    "value",
    ["abc", "3d97dc6c-5a9e-490b-8a33-413904685ba9", "req_1.2-3", "A" * 128, "a", str(uuid.uuid4().hex)],
)
def test_safe_request_ids_are_accepted(value):
    assert is_valid_request_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "A" * 129,
        "has space",
        "tab\there",
        "line\nbreak",
        "кириллица",
        "semi;colon",
        "a/b",
        "a:b",
        "<script>",
        '"quote"',
    ],
)
def test_unsafe_request_ids_are_rejected(value):
    assert not is_valid_request_id(value)


def _run(rf, header=None, traceparent=None):
    seen = {}

    def get_response(request):
        seen["request_id"] = request.request_id
        seen["correlation"] = get_correlation_id()
        seen["traceparent"] = get_traceparent()
        return HttpResponse("ok")

    extra = {}
    if header is not None:
        extra["HTTP_X_REQUEST_ID"] = header
    if traceparent is not None:
        extra["HTTP_TRACEPARENT"] = traceparent
    response = RequestIDMiddleware(get_response)(rf.get("/x", **extra))
    return response, seen


def test_valid_inbound_id_is_kept_and_echoed(rf):
    response, seen = _run(rf, "client-req-77")
    assert seen["request_id"] == "client-req-77" == response["X-Request-ID"] == seen["correlation"]


@pytest.mark.parametrize("bad", ["x" * 200, "with space", "<b>bold</b>", "кириллица"])
def test_unsafe_inbound_id_is_replaced_by_a_new_uuid(rf, bad):
    response, seen = _run(rf, bad)
    assert re.fullmatch(r"[0-9a-f]{32}", seen["request_id"]), "новый UUID, а не чужая строка"
    assert response["X-Request-ID"] == seen["request_id"] == seen["correlation"]
    assert bad not in response["X-Request-ID"]


def test_no_inbound_id_gets_a_fresh_one_and_the_context_does_not_leak(rf):
    first, _ = _run(rf)
    second, seen = _run(rf)
    assert first["X-Request-ID"] != second["X-Request-ID"] and seen["request_id"] == second["X-Request-ID"]
    assert get_correlation_id() is None, "после запроса корреляция сброшена"


def test_traceparent_travels_with_the_request(rf):
    _, seen = _run(rf, "abc", TRACEPARENT)
    assert seen["traceparent"] == TRACEPARENT
    _, bad = _run(rf, "abc", "not-a-traceparent")
    assert bad["traceparent"] is None


@pytest.mark.django_db
def test_the_request_id_is_the_correlationid_of_an_event_published_in_the_request(rf):
    company = make_company(crm_client_id=42)

    def get_response(request):
        with transaction.atomic():
            events.publish_event("invite.sent", company.pk, {"channels": ["email"]})
        return HttpResponse("ok")

    RequestIDMiddleware(get_response)(rf.get("/x", HTTP_X_REQUEST_ID="req-from-caddy", HTTP_TRACEPARENT=TRACEPARENT))

    envelope = bus_support.only("invite.sent")
    assert envelope["correlationid"] == "req-from-caddy"
    assert envelope["traceparent"] == TRACEPARENT


@pytest.mark.django_db
def test_an_unsafe_request_id_never_reaches_the_event(rf):
    company = make_company(crm_client_id=42)
    holder = {}

    def get_response(request):
        holder["id"] = request.request_id
        with transaction.atomic():
            events.publish_event("invite.sent", company.pk, {"channels": ["email"]})
        return HttpResponse("ok")

    RequestIDMiddleware(get_response)(rf.get("/x", HTTP_X_REQUEST_ID="evil value\twith spaces"))
    assert bus_support.only("invite.sent")["correlationid"] == holder["id"]
    assert "evil" not in holder["id"]


@pytest.mark.django_db
def test_event_outside_a_request_gets_a_new_uuid():
    company = make_company(crm_client_id=42)
    CrmClientMapping.objects.filter(company=company).update(crm_client_id=43)
    with transaction.atomic():
        events.publish_event("invite.sent", company.pk, {"channels": ["email"]})
    assert re.fullmatch(r"[0-9a-f-]{36}", bus_support.only("invite.sent")["correlationid"])
