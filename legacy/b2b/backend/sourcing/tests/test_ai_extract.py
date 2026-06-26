"""AI #6 contract/invoice extraction — code-side reconciliation flags money mismatches.

The Claude client is stubbed (no paid/nondeterministic calls). We assert the deterministic
trusted side: the `reconcile` helper recomputes the comparison in Decimal and flags a total
mismatch, a foreign/unknown currency and an expired document — never trusting LLM numbers.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from master_data.models import Currency


def _stub_response(payload):
    text = __import__("json").dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.mark.django_db
def test_reconcile_flags_total_mismatch():
    """Document total ≠ КП total → TOTAL_MISMATCH, computed in code with Decimal."""
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узб. сум", "is_active": True})
    extracted = {
        "total": "1 234 567,89",  # comma + spaces — code parses to Decimal('1234567.89')
        "currency_code": "UZS",
        "valid_until": "",
        "bank_details": "Bank X",
        "line_totals": [],
    }
    from sourcing.services_ai_extract import reconcile

    result = reconcile(extracted, expected_total=Decimal("1000000.00"), expected_currency_code="UZS")
    codes = [m["code"] for m in result["mismatches"]]
    assert "TOTAL_MISMATCH" in codes
    assert result["ok"] is False
    flag = next(m for m in result["mismatches"] if m["code"] == "TOTAL_MISMATCH")
    assert flag["document_total"] == "1234567.89"
    assert flag["expected_total"] == "1000000.00"


@pytest.mark.django_db
def test_reconcile_clean_when_total_matches():
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узб. сум", "is_active": True})
    extracted = {
        "total": "1000000.00",
        "currency_code": "UZS",
        "valid_until": (date.today() + timedelta(days=10)).isoformat(),
        "bank_details": "",
        "line_totals": [],
    }
    from sourcing.services_ai_extract import reconcile

    result = reconcile(extracted, expected_total=Decimal("1000000.00"), expected_currency_code="UZS")
    assert result["ok"] is True
    assert result["mismatches"] == []


@pytest.mark.django_db
def test_reconcile_flags_foreign_and_unknown_currency():
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узб. сум", "is_active": True})
    Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "is_active": True})
    from sourcing.services_ai_extract import reconcile

    # USD is a valid code but differs from the КП currency UZS → FOREIGN_CURRENCY.
    foreign = reconcile(
        {"total": "100", "currency_code": "USD", "valid_until": "", "bank_details": "", "line_totals": []},
        expected_total=Decimal("100"),
        expected_currency_code="UZS",
    )
    assert "FOREIGN_CURRENCY" in [m["code"] for m in foreign["mismatches"]]

    # XYZ is not in the справочник → CURRENCY_UNKNOWN.
    unknown = reconcile(
        {"total": "100", "currency_code": "XYZ", "valid_until": "", "bank_details": "", "line_totals": []},
        expected_total=Decimal("100"),
        expected_currency_code="UZS",
    )
    assert "CURRENCY_UNKNOWN" in [m["code"] for m in unknown["mismatches"]]


@pytest.mark.django_db
def test_reconcile_flags_expired_document():
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узб. сум", "is_active": True})
    from sourcing.services_ai_extract import reconcile

    result = reconcile(
        {
            "total": "100",
            "currency_code": "UZS",
            "valid_until": (date.today() - timedelta(days=1)).isoformat(),
            "bank_details": "",
            "line_totals": [],
        },
        expected_total=Decimal("100"),
        expected_currency_code="UZS",
    )
    assert "DOCUMENT_EXPIRED" in [m["code"] for m in result["mismatches"]]


@pytest.mark.django_db
def test_extract_document_fields_disabled_raises(settings):
    settings.AI_IMPORT_ENABLED = False
    from sourcing.services_ai_extract import extract_document_fields

    with pytest.raises(RuntimeError, match="AI_IMPORT_DISABLED"):
        extract_document_fields(b"%PDF-1.4 fake", "contract.pdf")


@pytest.mark.django_db
def test_extract_document_fields_parses_stubbed_model(settings, monkeypatch):
    """Stub the Claude client; assert the structured shape is normalised (upper currency,
    bounded strings) — the model output is treated as untrusted OCR, parsed in code."""
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        {
            "total": "1234567.89",
            "currency_code": "usd",  # lower-cased by the model → normalised to USD
            "valid_until": "2030-01-01",
            "bank_details": "Bank X, acct 123",
            "line_totals": [{"description": "Болт М12", "line_total": "100.00"}],
        }
    )
    monkeypatch.setattr(
        "sourcing.services_ai_extract._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from sourcing.services_ai_extract import extract_document_fields

    fields = extract_document_fields(b"%PDF-1.4 fake", "contract.pdf")
    assert fields["total"] == "1234567.89"
    assert fields["currency_code"] == "USD"
    assert fields["valid_until"] == "2030-01-01"
    assert len(fields["line_totals"]) == 1
    assert fields["line_totals"][0]["description"] == "Болт М12"


@pytest.mark.django_db
def test_extract_endpoint_guards(settings, monkeypatch):
    """Endpoint guard contract: AI-disabled, missing file, and unsupported file-type all return
    BEFORE the paid Claude call (spy fails if reached). The new type allowlist rejects arbitrary
    binaries that file_to_payload would otherwise decode as garbage and still bill a call."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from rest_framework.test import APIClient

    import sourcing.services_ai_extract as ext
    from accounts.models import CustomUser

    monkeypatch.setattr(ext, "_client", lambda: pytest.fail("paid call reached on a guarded extract path"))
    user = CustomUser.objects.create_user(email="dx@x.test", username="dx@x.test", password="pw", is_active=True)
    client = APIClient()
    client.force_authenticate(user)
    url = "/api/v1/sourcing/extract-document/"

    # AI disabled → 503, before the file is even read
    settings.AI_IMPORT_ENABLED = False
    pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 stub", content_type="application/pdf")
    assert client.post(url, {"file": pdf, "quote_id": 1}, format="multipart").status_code == 503

    settings.AI_IMPORT_ENABLED = True
    # missing file → 400
    assert client.post(url, {"quote_id": 1}, format="multipart").status_code == 400
    # unsupported type → 400 FILE_TYPE_UNSUPPORTED (allowlist), call never reached
    binary = SimpleUploadedFile("malware.exe", b"MZ\x00\x00binary", content_type="application/octet-stream")
    resp = client.post(url, {"file": binary, "quote_id": 1}, format="multipart")
    assert resp.status_code == 400
    assert resp.json().get("error") == "FILE_TYPE_UNSUPPORTED"
