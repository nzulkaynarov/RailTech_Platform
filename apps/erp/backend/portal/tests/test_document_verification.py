"""Tests for public document verification endpoint (GET /api/portal/v1/verify/{code}).

ADR-0024 §6, SIGN-VERIFY-1:
- Public endpoint without auth or session;
- Returns document details, signatory, authority basis, and SHA-256 hash;
- Returns 404 {"detail": "NOT_FOUND"} for unknown code;
- Rate limited per IP (scope portal_verify).
"""

from datetime import date

import pytest
from django.utils import timezone
from portal.models import PortalDocumentVerification
from rest_framework import status
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def valid_doc(db):
    return PortalDocumentVerification.objects.create(
        code="doc-verify-12345",
        kind="letter_out",
        number="ИСХ-042/26",
        date=date(2026, 11, 5),
        company_name="OOO «RailTech»",
        signatory_name="Иванов Иван Иванович",
        signatory_position="Генеральный директор",
        signatory_basis="на основании Устава",
        status="valid",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        signed_at=timezone.now(),
    )


@pytest.fixture
def revoked_doc(db):
    return PortalDocumentVerification.objects.create(
        code="doc-revoked-99999",
        kind="letter_out",
        number="ИСХ-011/26",
        date=date(2026, 10, 1),
        company_name="OOO «RailTech»",
        signatory_name="Петров Петр Петрович",
        signatory_position="Заместитель директора",
        signatory_basis="по доверенности № 12/25 от 01.12.2025",
        status="revoked",
        sha256_hash="01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
        signed_at=timezone.now(),
        revoked_at=timezone.now(),
        revocation_reason="Документ отозван в связи с аннулированием доверенности",
    )


@pytest.mark.django_db
def test_verify_document_success(api_client, valid_doc):
    """200 OK — валидный документ со всеми полями."""
    response = api_client.get(f"/api/portal/v1/verify/{valid_doc.code}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["code"] == "doc-verify-12345"
    assert data["kind"] == "letter_out"
    assert data["number"] == "ИСХ-042/26"
    assert data["date"] == "2026-11-05"
    assert data["company_name"] == "OOO «RailTech»"
    assert data["signatory_name"] == "Иванов Иван Иванович"
    assert data["signatory_position"] == "Генеральный директор"
    assert data["signatory_basis"] == "на основании Устава"
    assert data["status"] == "valid"
    assert data["sha256_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert data["signed_at"] is not None
    assert data["revoked_at"] is None


@pytest.mark.django_db
def test_verify_document_revoked(api_client, revoked_doc):
    """200 OK — отозванный документ содержит причину и дату отзыва."""
    response = api_client.get(f"/api/portal/v1/verify/{revoked_doc.code}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["code"] == "doc-revoked-99999"
    assert data["status"] == "revoked"
    assert data["revoked_at"] is not None
    assert data["revocation_reason"] == "Документ отозван в связи с аннулированием доверенности"


@pytest.mark.django_db
def test_verify_document_not_found(api_client):
    """404 NOT_FOUND — неизвестный код."""
    response = api_client.get("/api/portal/v1/verify/unknown-code-999")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "NOT_FOUND"}


@pytest.mark.django_db
def test_verify_document_slash_optional(api_client, valid_doc):
    """Маршрут со слешем и без слеша работает одинаково."""
    response = api_client.get(f"/api/portal/v1/verify/{valid_doc.code}/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["code"] == valid_doc.code


@pytest.mark.django_db
def test_verify_document_rate_limit(api_client, valid_doc, monkeypatch):
    """429 TOO_MANY_REQUESTS — при превышении лимита portal_verify."""
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "portal_verify", "2/minute")

    res1 = api_client.get(f"/api/portal/v1/verify/{valid_doc.code}")
    assert res1.status_code == status.HTTP_200_OK

    res2 = api_client.get(f"/api/portal/v1/verify/{valid_doc.code}")
    assert res2.status_code == status.HTTP_200_OK

    res3 = api_client.get(f"/api/portal/v1/verify/{valid_doc.code}")
    assert res3.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert res3.json() == {"detail": "TOO_MANY_REQUESTS"}
    assert "Retry-After" in res3.headers
