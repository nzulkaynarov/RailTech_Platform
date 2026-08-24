"""
Заявку на роль, поданную из продукта, стало возможно провести.

Замер 24-08: форма подачи не спрашивала документов — заявка уходила с
`contract_file:null, nda_file:null`, а `approve` отбивал её кодом
`ROLE_APPLICATION_MISSING_CONTRACT_NDA`. Оператор видел в меню только «Одобрить» и
«Отклонить»: статус `DOCUMENTS_REQUIRED` в модели был, но поставить его было нечем, а если бы
и поставили — приложить документы заявителю было негде (`perform_update` пускал только
`PENDING`). Цикл замыкался в тупик с обеих сторон.

Эталон — Stripe verification «information needed» и Salesforce «Request more info»: запросили
недостающее → заявитель донёс → запись вернулась в очередь на рассмотрение.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRoleApplication,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _pdf(name):
    return SimpleUploadedFile(name, b"%PDF-1.4 ok", content_type="application/pdf")


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier"), ("MANUFACTURER", "Manufacturer")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})

    company = Company.objects.create(
        name="Заявитель",
        inn="907700001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    owner = CustomUser.objects.create_user(
        email="owner@application.test", username="owner_app", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=owner,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    operator = CustomUser.objects.create_user(
        email="operator@application.test",
        username="operator_app",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
        is_superuser=True,
    )
    return {"company": company, "owner": owner, "operator": operator}


def _submit(world, **files):
    payload = {
        "company": world["company"].pk,
        "requested_type": CompanyType.objects.get(code="SUPPLIER").pk,
        **files,
    }
    return _api(world["owner"]).post("/api/v1/accounts/role-applications/", payload, format="multipart")


# ── Подача с документами ────────────────────────────────────────────────────


def test_application_submitted_with_documents_can_be_approved(world):
    """Тот самый путь, который был замкнут: подал → одобрили."""
    resp = _submit(world, contract_file=_pdf("contract.pdf"), nda_file=_pdf("nda.pdf"))
    assert resp.status_code == 201, resp.content

    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    approve = _api(world["operator"]).post(f"/api/v1/accounts/role-applications/{application.pk}/approve/")

    assert approve.status_code == 200, approve.content
    application.refresh_from_db()
    assert application.status == "APPROVED"
    assert world["company"].types.filter(code="SUPPLIER").exists()


def test_missing_documents_predicate_names_the_fields(world):
    from accounts.services import missing_application_documents

    application = CompanyRoleApplication.objects.create(
        company=world["company"],
        requested_type=CompanyType.objects.get(code="SUPPLIER"),
        submitted_by=world["owner"],
        status="PENDING",
    )

    assert missing_application_documents(application) == ["contract_file", "nda_file"]

    application.contract_file = _pdf("c.pdf")
    application.save(update_fields=["contract_file"])
    assert missing_application_documents(application) == ["nda_file"]


# ── Оператор просит недостающее вместо отказа ───────────────────────────────


def test_operator_can_request_documents_instead_of_rejecting(world):
    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])

    request_docs = _api(world["operator"]).post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "нужны договор и NDA"},
        format="json",
    )

    assert request_docs.status_code == 200, request_docs.content
    application.refresh_from_db()
    assert application.status == "DOCUMENTS_REQUIRED"
    assert application.review_notes == "нужны договор и NDA"


def test_requesting_documents_leaves_a_trace(world):
    from crm.models import ActivityLog

    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    _api(world["operator"]).post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "нет NDA"},
        format="json",
    )

    entry = ActivityLog.objects.get(entity_type="role_application", entity_id=application.pk)
    assert entry.event_code.startswith("admin."), "иначе «Журнал доступа» запись не покажет"
    assert entry.reason == "нет NDA"


def test_documents_cannot_be_requested_twice(world):
    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    api = _api(world["operator"])
    api.post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "раз"},
        format="json",
    )

    second = api.post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "два"},
        format="json",
    )

    assert second.status_code == 400
    assert second.json()["detail"] == "ROLE_APPLICATION_CANNOT_REQUEST_DOCS"


# ── Заявитель доносит документы, заявка возвращается в очередь ──────────────


def test_applicant_can_attach_documents_after_they_were_requested(world):
    """До 24-08 `perform_update` пускал только `PENDING`: оператор просил документы, а
    приложить их было НЕГДЕ — статус превращался в тупик."""
    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    _api(world["operator"]).post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "нужны оба"},
        format="json",
    )

    upload = _api(world["owner"]).patch(
        f"/api/v1/accounts/role-applications/{application.pk}/",
        {"contract_file": _pdf("contract.pdf"), "nda_file": _pdf("nda.pdf")},
        format="multipart",
    )

    assert upload.status_code == 200, upload.content
    application.refresh_from_db()
    assert application.contract_file and application.nda_file
    # Донёс всё — заявка снова в очереди: иначе она молча висит, и оператор не узнает,
    # что ждать больше нечего.
    assert application.status == "PENDING"


def test_partial_upload_keeps_the_application_waiting(world):
    """Донёс половину — статус не меняется: очередь не должна получать неполную заявку."""
    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    _api(world["operator"]).post(
        f"/api/v1/accounts/role-applications/{application.pk}/request-documents/",
        {"reason": "нужны оба"},
        format="json",
    )

    upload = _api(world["owner"]).patch(
        f"/api/v1/accounts/role-applications/{application.pk}/",
        {"contract_file": _pdf("contract.pdf")},
        format="multipart",
    )

    # Загрузка ПРОШЛА (иначе тест был бы зелёным и на старом коде, где заявителю PATCH
    # запрещён вовсе), но статус не изменился — заявка ждёт второго документа.
    assert upload.status_code == 200, upload.content
    application.refresh_from_db()
    assert application.contract_file
    assert application.status == "DOCUMENTS_REQUIRED"


def test_decided_application_cannot_be_edited_by_the_applicant(world):
    """Обратная сторона: рассмотренную заявку заявитель не правит."""
    resp = _submit(world, contract_file=_pdf("c.pdf"), nda_file=_pdf("n.pdf"))
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])
    _api(world["operator"]).post(f"/api/v1/accounts/role-applications/{application.pk}/approve/")

    upload = _api(world["owner"]).patch(
        f"/api/v1/accounts/role-applications/{application.pk}/",
        {"contract_file": _pdf("other.pdf")},
        format="multipart",
    )

    assert upload.status_code == 403


def test_approve_still_refuses_an_application_without_documents(world):
    """Гейт документов НЕ ослаблен — он остался ровно там, где был."""
    resp = _submit(world)
    application = CompanyRoleApplication.objects.get(pk=resp.json()["id"])

    approve = _api(world["operator"]).post(f"/api/v1/accounts/role-applications/{application.pk}/approve/")

    assert approve.status_code == 400
    assert approve.json()["detail"] == "ROLE_APPLICATION_MISSING_CONTRACT_NDA"
