"""E2 — проверка целостности шаблона юридического вида (spec-editable-outgoing-documents).

Аналог «lock block position» у PandaDoc: активировать шаблон договора/счёта/акта без
структурных блоков нельзя — без таблицы позиций, итогов и подписей/реквизитов документ
перестаёт быть документом. Черновик правится свободно; проверка срабатывает на активации.

Плюс контракт формы ошибки: серверная валидация шаблонов обязана отвечать
`{"detail": "<CODE>"}` — до E2 DjangoValidationError долетала до Django как HTML-страница
«Bad Request», которую SPA не мог ни разобрать, ни перевести.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import DocumentTemplate, DocumentTemplateKind
from crm.services.document_blocks import (
    REQUIRED_TEMPLATE_BLOCKS,
    company_template_for,
    missing_required_blocks,
)


@pytest.fixture
def lookups(db):
    from crm.models import DocumentTemplateKind

    for code, name in (
        ("LETTER", "Письмо"),
        ("CUSTOM", "Произвольный"),
        ("CONTRACT", "Договор"),
        ("INVOICE", "Счёт"),
        ("ACT", "Акт"),
    ):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})


def _seller(email="owner@integrity.test"):
    company = Company.objects.create(name="Продавец", inn="9911000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return company, user, client


def test_missing_blocks_names_exactly_what_is_absent():
    body = "<p>текст</p>{{doc.totals}}"
    assert missing_required_blocks("CONTRACT", body) == ["doc.spec_table", "doc.requisites_and_signatures"]
    assert missing_required_blocks("LETTER", "<p>что угодно</p>") == []


@pytest.mark.django_db
def test_legal_template_cannot_be_created_without_required_blocks(lookups):
    _company, _user, client = _seller()
    resp = client.post(
        "/api/v1/crm/document-templates/",
        {"name": "Наш договор", "kind": "CONTRACT", "body_html": "<p>только текст</p>"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TEMPLATE_MISSING_REQUIRED_BLOCKS"


@pytest.mark.django_db
def test_activation_is_blocked_until_blocks_are_inserted(lookups):
    company, user, client = _seller()
    from crm.services.generated_documents import update_template

    template = DocumentTemplate.objects.create(
        company=company,
        name="Черновик акта",
        kind=DocumentTemplateKind.objects.get(code="ACT"),
        body_html="<p>пусто</p>",
        is_active=False,
    )
    # Черновик правится свободно.
    update_template(template, body_html="<p>всё ещё пусто</p>")

    resp = client.patch(f"/api/v1/crm/document-templates/{template.id}/", {"is_active": True}, format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TEMPLATE_MISSING_REQUIRED_BLOCKS"

    body = "<p>Акт</p>{{doc.items_table}}{{doc.totals}}{{doc.signatures}}"
    resp = client.patch(
        f"/api/v1/crm/document-templates/{template.id}/", {"body_html": body, "is_active": True}, format="json"
    )
    assert resp.status_code == 200, resp.content
    template.refresh_from_db()
    assert template.is_active is True


@pytest.mark.django_db
def test_platform_samples_pass_their_own_integrity_check():
    """Образцы, которые сеет миграция, обязаны проходить проверку — иначе «скопировать к себе»
    рождает шаблон, который нельзя активировать."""
    for kind in REQUIRED_TEMPLATE_BLOCKS:
        sample = company_template_for(None, kind)
        assert sample is not None, kind
        assert missing_required_blocks(kind, sample.body_html) == [], kind


@pytest.mark.django_db
def test_copy_of_a_legal_sample_succeeds(lookups):
    """Rule 1: образец из миграции копируется без ошибок целостности."""
    _company_, _user, client = _seller()
    sample = company_template_for(None, "INVOICE")
    resp = client.post(f"/api/v1/crm/document-templates/{sample.id}/copy/")
    assert resp.status_code == 201, resp.content
    assert resp.json()["kind_code"] == "INVOICE"


@pytest.mark.django_db
def test_non_legal_kinds_are_untouched_by_the_check(lookups):
    _company_, _user, client = _seller()
    resp = client.post(
        "/api/v1/crm/document-templates/",
        {"name": "Письмо", "kind": "LETTER", "body_html": "<p>свободный текст</p>"},
        format="json",
    )
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_service_validation_errors_answer_as_detail_code_not_html(lookups):
    """Контракт формы ошибки: {"detail": CODE}, а не django-страница Bad Request."""
    _company_, _user, client = _seller()
    resp = client.post(
        "/api/v1/crm/document-templates/",
        {"name": "", "kind": "CUSTOM", "body_html": "x"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TEMPLATE_NAME_REQUIRED"


@pytest.mark.django_db
def test_placeholders_endpoint_serves_required_blocks(lookups):
    _company_, _user, client = _seller()
    resp = client.get("/api/v1/crm/document-templates/placeholders/")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["required_blocks"] == {kind: list(codes) for kind, codes in REQUIRED_TEMPLATE_BLOCKS.items()}
