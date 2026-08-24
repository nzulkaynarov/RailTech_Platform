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
    """Owner decision 2026-06-03: approval no longer needs uploaded docs — но остаётся
    «предупреждение + обоснование», поэтому у выдачи без доказательств есть причина."""
    company = company_factory()  # starts L1_UNVERIFIED
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    result, err = acc_services.verify_company_kyc(
        company, approver, "L2_VERIFIED", require_documents=False, reason="проверено по реестру ГНК"
    )
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
    acc_services.verify_company_kyc(
        company, approver, "L2_VERIFIED", require_documents=False, reason="подготовка теста: выдать уровень"
    )
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
    approved, skipped = acc_services.bulk_verify_kyc(qs, approver, "L2_VERIFIED", reason="пакет проверен вручную")
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


# ─────────────────────────────────────────────────────────────────────────────
# Гейт обоснования и равный уровень — находки прогона 20-08 №11, №12, №13.
#
# Оба правила проверяются НА КАЖДОМ пути, а не только в сервисе: до 24-08 обоснование
# требовал один диалог из четырёх, и любой другой путь его обходил. Тест на сервис такую
# дыру не видит — он и был бы зелёным.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_evidence_gaps_name_what_is_missing(verification_levels, company_factory):
    company = company_factory(inn="")
    assert acc_services.kyc_evidence_gaps(company) == ["NO_DOCUMENTS", "NO_INN"]

    with_docs = company_factory(name="Docs", inn="7770000001", email="docs@example.com")
    acc_services.upload_kyc_document(
        with_docs, SimpleUploadedFile("charter.pdf", b"%PDF-1.4 ok", content_type="application/pdf"), "OTHER"
    )
    assert acc_services.kyc_evidence_gaps(with_docs) == []


@pytest.mark.django_db
def test_l2_without_evidence_needs_reason(verification_levels, company_factory, user_factory):
    company = company_factory()  # ИНН есть, документов ноль
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)

    _, err = acc_services.verify_company_kyc(company, approver, "L2_VERIFIED", require_documents=False, reason="")
    assert err == "KYC_REASON_REQUIRED_WITHOUT_EVIDENCE"
    company.refresh_from_db()
    assert company.verification_status.code == "L1_UNVERIFIED", "отказ обязан ничего не менять"
    assert company.is_verified is False


@pytest.mark.django_db
def test_l2_with_documents_needs_no_reason(verification_levels, company_factory, user_factory):
    """Обратная сторона: гейт не превращается в «нельзя никому» — доказательства есть,
    обоснование не нужно."""
    company = company_factory()
    acc_services.upload_kyc_document(
        company, SimpleUploadedFile("charter.pdf", b"%PDF-1.4 ok", content_type="application/pdf"), "OTHER"
    )
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)
    result, err = acc_services.verify_company_kyc(company, approver, "L2_VERIFIED", require_documents=False)
    assert err is None
    assert result.verification_status.code == "L2_VERIFIED"


@pytest.mark.django_db
def test_same_level_changes_nothing_and_writes_no_log(verification_levels, company_factory, user_factory):
    """«Отозвать верификацию» на компании, которая и так в L1: до починки путь писал в журнал
    зелёную запись об успехе и рассылал письма о смене статуса."""
    from crm.models import ActivityLog

    company = company_factory()
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)

    result, err = acc_services.verify_company_kyc(
        company, approver, "L1_UNVERIFIED", require_documents=False, reason="жалоба клиента"
    )
    assert err == "KYC_LEVEL_UNCHANGED"
    assert result is None
    assert not ActivityLog.objects.filter(entity_type="company", entity_id=company.id).exists()


@pytest.mark.django_db
def test_bulk_reports_companies_without_evidence_instead_of_approving(
    verification_levels, company_factory, user_factory
):
    """Массовый путь шёл мимо обоснования и одобрял всех — теперь такие компании попадают
    в `skipped` с кодом, а не в L2 с пустым reason."""
    from accounts.models import Company

    bare = company_factory(name="Без документов", inn="3333333333", email="bare@example.com")
    documented = company_factory(name="С документами", inn="4444444444", email="doc@example.com")
    acc_services.upload_kyc_document(
        documented, SimpleUploadedFile("charter.pdf", b"%PDF-1.4 ok", content_type="application/pdf"), "OTHER"
    )
    approver = user_factory(email="admin@example.com", username="admin", is_staff=True)

    qs = Company.objects.filter(id__in=[bare.id, documented.id])
    approved, skipped = acc_services.bulk_verify_kyc(qs, approver, "L2_VERIFIED", reason="")

    assert approved == 1
    assert [(item["name"], item["error"]) for item in skipped] == [
        ("Без документов", "KYC_REASON_REQUIRED_WITHOUT_EVIDENCE")
    ]
    bare.refresh_from_db()
    assert bare.verification_status.code == "L1_UNVERIFIED"

    # С обоснованием тот же пакет проходит целиком — политика владельца сохранена.
    approved2, skipped2 = acc_services.bulk_verify_kyc(
        Company.objects.filter(id=bare.id), approver, "L2_VERIFIED", reason="учредительные придут позже"
    )
    assert (approved2, skipped2) == (1, [])
