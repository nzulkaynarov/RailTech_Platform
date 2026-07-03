"""
Service-level tests for accounts KYC logic (CLAUDE.md "Known test debt").

Covers verify_company_kyc level transitions + guards, bulk_verify_kyc, and
upload_kyc_document validation — the moderation actions the Platform Admin
relies on. Uses the root conftest user_factory / company_factory fixtures.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts import services as acc_services
from accounts.models import KYCDocType, VerificationStatus


@pytest.fixture
def verification_levels(db):
    for code, name, rank in [
        ("L1_UNVERIFIED", "L1", 10),
        ("PROFILE_SUBMITTED", "Submitted", 20),
        ("L2_VERIFIED", "L2", 30),
        ("L3_CONTRACTED", "L3", 40),
    ]:
        VerificationStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": rank})
    KYCDocType.objects.get_or_create(code="OTHER", defaults={"name": "Other", "sort_order": 10})


@pytest.mark.django_db
def test_verify_company_kyc_upgrade_without_documents(verification_levels, company_factory, user_factory):
    """Owner decision 2026-06-03: approval no longer needs uploaded docs."""
    company = company_factory()  # starts L1_UNVERIFIED
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    result, err = acc_services.verify_company_kyc(company, approver, "L2_VERIFIED", require_documents=False)
    assert err is None
    assert result.verification_status.code == "L2_VERIFIED"


@pytest.mark.django_db
def test_verify_company_kyc_requires_documents_when_asked(verification_levels, company_factory, user_factory):
    company = company_factory()
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    _, err = acc_services.verify_company_kyc(company, approver, "L2_VERIFIED", require_documents=True)
    assert err == "KYC_DOCUMENTS_MISSING"


@pytest.mark.django_db
def test_verify_company_kyc_downgrade_needs_reason(verification_levels, company_factory, user_factory):
    company = company_factory()
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    acc_services.verify_company_kyc(company, approver, "L2_VERIFIED", require_documents=False)
    # Revoking down to L1 without a reason must be refused (audit requirement).
    _, err = acc_services.verify_company_kyc(company, approver, "L1_UNVERIFIED", reason="")
    assert err == "REASON_REQUIRED"
    company2, err2 = acc_services.verify_company_kyc(company, approver, "L1_UNVERIFIED", reason="fraud suspected")
    assert err2 is None
    assert company2.verification_status.code == "L1_UNVERIFIED"


@pytest.mark.django_db
def test_verify_company_kyc_unknown_level(verification_levels, company_factory, user_factory):
    company = company_factory()
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    _, err = acc_services.verify_company_kyc(company, approver, "NOPE")
    assert err == "VERIFICATION_STATUS_NOT_FOUND"


@pytest.mark.django_db
def test_bulk_verify_kyc_approves_all(verification_levels, company_factory, user_factory):
    c1 = company_factory(name="A", inn="1111111111", email="a@example.com")
    c2 = company_factory(name="B", inn="2222222222", email="b@example.com")
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    from accounts.models import Company

    qs = Company.objects.filter(id__in=[c1.id, c2.id])
    approved, skipped = acc_services.bulk_verify_kyc(qs, approver, "L2_VERIFIED")
    assert approved == 2
    assert skipped == []


@pytest.mark.django_db
def test_upload_kyc_document_rejects_bad_extension(verification_levels, company_factory):
    company = company_factory()
    bad = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/octet-stream")
    doc, err = acc_services.upload_kyc_document(company, bad, "OTHER")
    assert doc is None
    assert err is not None


@pytest.mark.django_db
def test_upload_kyc_document_accepts_pdf(verification_levels, company_factory):
    company = company_factory()
    pdf = SimpleUploadedFile("charter.pdf", b"%PDF-1.4 minimal", content_type="application/pdf")
    doc, err = acc_services.upload_kyc_document(company, pdf, "OTHER")
    assert err is None
    assert doc is not None
    assert company.kyc_documents.count() == 1


@pytest.mark.django_db
def test_upload_kyc_document_rejects_content_spoof(verification_levels, company_factory):
    # SEC-08: an allowed extension (.pdf) whose body is NOT a PDF (here PNG bytes) must be
    # rejected by the magic-byte check, not stored as a "document".
    company = company_factory()
    spoof = SimpleUploadedFile("charter.pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, content_type="application/pdf")
    doc, err = acc_services.upload_kyc_document(company, spoof, "OTHER")
    assert doc is None
    assert err is not None
    assert company.kyc_documents.count() == 0
