"""AI #6 contract/invoice extraction — code-side reconciliation flags money mismatches.

The LiteLLM gateway is faked (ai.testing.FakeGateway) (no paid/nondeterministic calls). We assert the deterministic
trusted side: the `reconcile` helper recomputes the comparison in Decimal and flags a total
mismatch, a foreign/unknown currency and an expired document — never trusting LLM numbers.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from master_data.models import Currency


def _staff(email, permissions=("quote.build",)):
    """Сотрудник своей компании с правом роли (M1-ERP-05: эндпоинт разбора документа — для
    `contract.manage` / `quote.build`)."""
    from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole

    company = Company.objects.create(name="Своя", inn=f"77{abs(hash(email)) % 10**7:07d}")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "S"})[0])
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    role = CompanyRole.objects.create(company=company, name="Роль", permissions=list(permissions))
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        is_primary=True,
        company_roles=[role],
    )
    return user


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
def test_extract_document_fields_parses_stubbed_model(fake_gateway):
    """Fake gateway; assert the structured shape is normalised (upper currency,
    bounded strings) — the model output is treated as untrusted OCR, parsed in code."""
    fake_gateway.reply_json(
        {
            "total": "1234567.89",
            "currency_code": "usd",  # lower-cased by the model → normalised to USD
            "valid_until": "2030-01-01",
            "bank_details": "Bank X, acct 123",
            "line_totals": [{"description": "Болт М12", "line_total": "100.00"}],
        }
    )
    from sourcing.services_ai_extract import extract_document_fields

    fields = extract_document_fields(b"%PDF-1.4 fake", "contract.pdf")
    assert fields["total"] == "1234567.89"
    assert fields["currency_code"] == "USD"
    assert fields["valid_until"] == "2030-01-01"
    assert len(fields["line_totals"]) == 1
    assert fields["line_totals"][0]["description"] == "Болт М12"
    body = fake_gateway.last_body
    assert body["model"] == "intake-model"
    # PDF едет блоком `file` в сообщении пользователя, а не в системном промпте; документ не
    # копируется в Langfuse (mask_input).
    assert body["messages"][1]["content"][0]["type"] == "file"
    assert body["metadata"]["mask_input"] is True


@pytest.mark.django_db
def test_extract_document_fields_gateway_down_raises_code(fake_gateway):
    """Шлюз недоступен — стабильный код для обработчика задачи (AI_EXTRACT_FAILED), не 500."""
    fake_gateway.reply_transport_error()
    from sourcing.services_ai_extract import extract_document_fields

    with pytest.raises(RuntimeError, match="AI_GATEWAY_UNAVAILABLE"):
        extract_document_fields(b"%PDF-1.4 fake", "contract.pdf")


@pytest.mark.django_db
def test_extract_endpoint_guards(settings, monkeypatch):
    """Endpoint guard contract: AI-disabled, missing file, and unsupported file-type all return
    BEFORE the paid Claude call (spy fails if reached). The new type allowlist rejects arbitrary
    binaries that file_to_payload would otherwise decode as garbage and still bill a call."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from rest_framework.test import APIClient

    # Корневой conftest блокирует транспорт шлюза: дошедший до модели guarded-путь упадёт.
    user = _staff("dx@x.test")
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
    assert resp.json().get("detail") == "FILE_TYPE_UNSUPPORTED"


@pytest.mark.django_db
def test_extract_endpoint_enqueues_202(settings, monkeypatch):
    """ARCH-01: a valid upload with a visible reference is queued on Celery — 202 {task_id}
    + an owned AIJob row. The document is staged in default_storage and only its KEY travels
    in the payload (bytes must never go through the Redis broker); expected values are
    resolved + JSON-serialized in the view (never the ORM)."""
    from django.core.files.storage import default_storage
    from django.core.files.uploadedfile import SimpleUploadedFile
    from rest_framework.test import APIClient

    from sourcing.models import AIJob

    settings.AI_IMPORT_ENABLED = True
    user = _staff("dx202@x.test")
    client = APIClient()
    client.force_authenticate(user)

    # The visibility-scoped record of truth is resolved in the view BEFORE enqueue.
    monkeypatch.setattr("sourcing.views_ai._resolve_expected", lambda *a: (Decimal("1000000.00"), "UZS", "quote"))
    captured = {}

    def _apply_async(args=None, task_id=None, **kwargs):
        captured.update(feature=args[0], payload=args[1], task_id=task_id)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", _apply_async)

    pdf = SimpleUploadedFile("contract.pdf", b"%PDF-1.4 stub", content_type="application/pdf")
    response = client.post("/api/v1/sourcing/extract-document/", {"file": pdf, "quote_id": 7}, format="multipart")

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert captured["task_id"] == task_id
    assert AIJob.objects.filter(celery_task_id=task_id, owner=user, feature="extract").exists()
    assert captured["feature"] == "extract"
    payload = captured["payload"]
    assert payload["filename"] == "contract.pdf"
    assert payload["expected_total"] == "1000000.00"  # Decimal serialized JSON-safe
    assert payload["expected_currency"] == "UZS"
    assert payload["kind"] == "quote"
    assert payload["reference_id"] == 7
    # Bytes staged in storage, not shipped through the broker.
    assert "file_b64" not in payload
    assert payload["file_key"].startswith("ai_extract_tmp/")
    try:
        with default_storage.open(payload["file_key"]) as staged:
            assert staged.read() == b"%PDF-1.4 stub"
    finally:
        default_storage.delete(payload["file_key"])
