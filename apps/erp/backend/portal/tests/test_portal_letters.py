"""Письма компании в кабинете — API портала (ЛИД-8, ADR-0026).

Только своя компания (чужое письмо — 404), фильтры списка, файл — только у исходящего; ERP берёт PDF у EDS по
сервисному токену: нет токена или EDS недоступен — 503 `LETTER_FILE_UNAVAILABLE`, у EDS файла нет — 404.
"""

from __future__ import annotations

import datetime
import uuid

import httpx
import pytest
from django.utils import timezone
from portal.models import LetterDirection, LetterState, PortalLetter
from portal.services import letters

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


def letter(company, direction=LetterDirection.OUT, number="OUT-007/26", **extra) -> PortalLetter:
    return PortalLetter.objects.create(
        company=company,
        direction=direction,
        state=LetterState.SENT if direction == LetterDirection.OUT else LetterState.REGISTERED,
        eds_id=uuid.uuid4(),
        number=number,
        subject=extra.pop("subject", "Ответ на запрос"),
        date=extra.pop("date", datetime.date(2026, 11, 16)),
        registered_at=timezone.now(),
        **extra,
    )


def test_list_shows_only_own_letters_with_filters(portal_client, client_company, other_company):
    out = letter(client_company)
    inbound = letter(client_company, LetterDirection.IN, "IN-104/26", subject="Запрос цены")
    letter(other_company, number="OUT-999/26")

    body = portal_client.get(f"{API}/letters").json()
    assert {row["number"] for row in body} == {"OUT-007/26", "IN-104/26"}
    row = next(row for row in body if row["id"] == out.pk)
    assert (row["has_file"], row["deal"], row["reply_number"]) == (True, None, None)

    assert [r["id"] for r in portal_client.get(f"{API}/letters", {"direction": "in"}).json()] == [inbound.pk]
    assert [r["id"] for r in portal_client.get(f"{API}/letters", {"q": "цены"}).json()] == [inbound.pk]
    assert portal_client.get(f"{API}/letters", {"date_from": "2026-11-17"}).json() == []
    assert portal_client.get(f"{API}/letters", {"direction": "sideways"}).status_code == 422
    assert portal_client.get(f"{API}/letters", {"date_to": "16.11.2026"}).status_code == 422


def test_foreign_letter_is_not_found(portal_client, other_company):
    foreign = letter(other_company)
    assert portal_client.get(f"{API}/letters/{foreign.pk}").status_code == 404
    assert portal_client.get(f"{API}/letters/{foreign.pk}/file").status_code == 404


def test_file_only_for_outgoing_via_eds(portal_client, client_company, settings, monkeypatch):
    out = letter(client_company)
    inbound = letter(client_company, LetterDirection.IN, "IN-104/26")
    assert portal_client.get(f"{API}/letters/{inbound.pk}/file").status_code == 404

    settings.SERVICE_TOKEN_ERP_TO_EDS = ""
    missing_token = portal_client.get(f"{API}/letters/{out.pk}/file")
    assert (missing_token.status_code, missing_token.json()["detail"]) == (503, "LETTER_FILE_UNAVAILABLE")

    settings.SERVICE_TOKEN_ERP_TO_EDS = "erp-to-eds-test-token"
    settings.EDS_INTERNAL_URL = "http://eds.test"
    seen: dict = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, auth=headers["Authorization"])
        return httpx.Response(200, content=b"%PDF-1.7 letter")

    monkeypatch.setattr(letters.httpx, "get", fake_get)
    response = portal_client.get(f"{API}/letters/{out.pk}/file")
    assert response.status_code == 200 and response.content == b"%PDF-1.7 letter"
    assert "OUT-007-26.pdf" in response["Content-Disposition"]
    assert seen == {
        "url": f"http://eds.test/api/v1/service/letters/{out.eds_id}/pdf",
        "auth": "Bearer erp-to-eds-test-token",
    }

    monkeypatch.setattr(letters.httpx, "get", lambda url, headers, timeout: httpx.Response(404))
    assert portal_client.get(f"{API}/letters/{out.pk}/file").status_code == 404

    def boom(url, headers, timeout):
        raise httpx.ConnectError("eds down")

    monkeypatch.setattr(letters.httpx, "get", boom)
    assert portal_client.get(f"{API}/letters/{out.pk}/file").status_code == 503
