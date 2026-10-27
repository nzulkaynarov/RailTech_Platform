"""D2-0 (B-011): справочники, шаблоны, нумерация, категории и курсы, которые BFF зовёт для «Admin · Компания».

Продолжение `test_openapi_company_conformance.py` (те же опоры): тела запросов — как шлёт BFF
(`schemas_company.py`), ответы — живые, сверяются с выгрузкой из кода. Поведение API файл не меняет.
"""

import datetime

import pytest

from accounts.models import CustomUser
from catalog.models import Category, CategoryRequest
from core.tests.openapi_internal import request_fields_missing
from core.tests.test_openapi_company_conformance import API, admin, company, conforms, sends  # noqa: F401
from master_data.models import Currency, DeliveryBasis

pytestmark = pytest.mark.django_db


# --- нумерация и условия КП -------------------------------------------------------------------------------------


def test_numbering_scheme_round_trip(admin, company):
    template = f"{API}crm/numbering-scheme/"
    conforms(admin.get(template.replace(API, API)), template, "get", status=200)
    body = {"pattern": "{prefix}-{type}-{year}-{seq}", "padding": 5, "reset_period": "yearly", "start_value": 0}
    sends(template, "patch", {**body, "type_labels": {"KP": "КП"}})
    response = admin.patch(template, {**body, "type_labels": {"KP": "КП"}}, format="json")
    conforms(response, template, "patch", status=200)
    refused = admin.patch(template, {"pattern": "no-seq-token"}, format="json")
    assert refused.json() == {"detail": "INVALID_NUMBERING_PATTERN"}
    conforms(refused, template, "patch", status=400)

    preview = f"{API}crm/numbering-scheme/preview/"
    draft = {**body, "type_labels": {"KP": "КП"}, "prefix": "D20"}
    sends(preview, "post", draft)
    conforms(admin.post(preview, draft, format="json"), preview, "post", status=200)


# --- статьи расхода ---------------------------------------------------------------------------------------------


def test_charge_types_and_templates_crud(admin, company):
    from crm.models import ChargeType

    conforms(admin.get(f"{API}crm/charge-types/"), f"{API}crm/charge-types/", "get", status=200)
    basis = DeliveryBasis.objects.get_or_create(code="EXW", defaults={"name": "EXW", "sort_order": 1})[0]
    charge = ChargeType.objects.first() or ChargeType.objects.create(code="FREIGHT", name="Фрахт", sort_order=1)
    listing = f"{API}crm/charge-templates/"
    conforms(admin.get(listing), listing, "get", status=200)
    body = {
        "delivery_basis": basis.code,
        "charge_type": charge.code,
        "default_amount": "10.00",
        "default_rate_percent": "2.50",
        "is_deduction": False,
        "sort_order": 1,
        "is_active": True,
    }
    sends(listing, "post", body)
    created = admin.post(listing, body, format="json")
    conforms(created, listing, "post", status=201)
    item = f"{API}crm/charge-templates/{{id}}/"
    one = f"{listing}{created.json()['id']}/"
    sends(item, "patch", {"default_amount": "11.00", "default_rate_percent": None, "is_active": False})
    conforms(admin.patch(one, {"default_amount": "11.00", "is_active": False}, format="json"), item, "patch", status=200)
    duplicate = admin.post(listing, body, format="json")
    conforms(duplicate, listing, "post", status=400)
    conforms(admin.delete(one), item, "delete", status=204)


# --- шаблоны документов -----------------------------------------------------------------------------------------

DOCUMENT_BODY = "<p>Договор {{contract_number}}</p>"


def test_document_templates_crud_and_refusals(admin, company):
    listing = f"{API}crm/document-templates/"
    item = f"{API}crm/document-templates/{{id}}/"
    conforms(admin.get(listing), listing, "get", status=200)
    conforms(
        admin.get(f"{listing}placeholders/"), f"{listing}placeholders/", "get", status=200
    )
    # BFF шлёт и `is_active`, но `create` его не принимает (шаблон рождается активным) — схема запроса честно
    # называет только name/kind/body_html; расхождение BFF ↔ ERP описано в QUESTIONS (Q-D20-1).
    body = {"name": "Мой шаблон", "body_html": DOCUMENT_BODY}
    sends(listing, "post", body)
    created = admin.post(listing, body, format="json")
    assert created.json()["is_active"] is True
    assert request_fields_missing(listing, "post", {"is_active": True}) == ["is_active"]
    conforms(created, listing, "post", status=201)
    one = f"{listing}{created.json()['id']}/"
    patch = {"name": "Мой шаблон 2", "body_html": DOCUMENT_BODY, "is_active": False}
    sends(item, "patch", patch)
    conforms(admin.patch(one, patch, format="json"), item, "patch", status=200)
    copy = admin.post(f"{one}copy/", {"name": "Копия"}, format="json")
    sends(f"{item}copy/", "post", {"name": "Копия"})
    conforms(copy, f"{item}copy/", "post", status=201)
    preview = admin.post(f"{listing}preview/", {"body_html": DOCUMENT_BODY}, format="json")
    sends(f"{listing}preview/", "post", {"body_html": DOCUMENT_BODY})
    conforms(preview, f"{listing}preview/", "post", status=200)
    conforms(admin.delete(one), item, "delete", status=204)


def test_active_legal_template_without_blocks_names_missing_blocks(admin, company):
    """B-011 (г): отказ `TEMPLATE_MISSING_REQUIRED_BLOCKS` несёт `missing_blocks` — и схема это говорит."""
    from crm.models import DocumentTemplateKind

    listing = f"{API}crm/document-templates/"
    kind = DocumentTemplateKind.objects.get(code="CONTRACT")
    response = admin.post(
        listing, {"name": "Договор", "kind": kind.code, "body_html": "<p>пусто</p>", "is_active": True}, format="json"
    )
    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "TEMPLATE_MISSING_REQUIRED_BLOCKS"
    assert body["missing_blocks"] and set(body["missing_blocks"][0]) == {"code", "label"}
    conforms(response, listing, "post", status=400)


# --- шаблоны писем ----------------------------------------------------------------------------------------------


def test_email_templates_crud_and_preview(admin, company):
    listing = f"{API}settings/email-templates/"
    item = f"{API}settings/email-templates/{{id}}/"
    conforms(admin.get(listing), listing, "get", status=200)
    body = {
        "key": "setup_password",
        "language": "ru",
        "subject": "Тема {{ name }}",
        "html_body": "<p>Привет, {{ name }}</p>",
        "text_body": "Привет, {{ name }}",
        "available_variables": "name",
        "is_active": True,
    }
    sends(listing, "post", body)
    created = admin.post(listing, body, format="json")
    conforms(created, listing, "post", status=201)
    one = f"{listing}{created.json()['id']}/"
    sends(item, "patch", {"subject": "Тема 2", "is_active": False})
    conforms(admin.patch(one, {"subject": "Тема 2", "is_active": False}, format="json"), item, "patch", status=200)
    preview = admin.post(f"{one}preview/", {}, format="json")
    conforms(preview, f"{item}preview/", "post", status=200)
    conforms(admin.delete(one), item, "delete", status=204)


# --- справочники ------------------------------------------------------------------------------------------------

REFERENCES = {
    "countries": {"code": "ZZ", "name": "Страна Зет", "alpha2": "ZZ", "alpha3": "ZZZ", "iso_numeric": "999", "vat_rate": "12.00"},
    "currencies": {"code": "ZZZ", "name": "Зет", "symbol": "Z"},
    "units": {"code": "zz", "name": "зет"},
    "delivery-basis": {
        "code": "ZZZ",
        "name": "Зет",
        "description": "d",
        "seller_pays_freight": True,
        "seller_pays_insurance": False,
        "seller_pays_import": False,
        "seller_pays_delivery": True,
    },
}


@pytest.mark.parametrize("kind", sorted(REFERENCES))
def test_reference_lists_crud(admin, company, kind):
    listing = f"{API}master-data/{kind}/"
    item = f"{API}master-data/{kind}/{{id}}/"
    conforms(admin.get(listing, {"include_inactive": "1", "page": 1, "page_size": 200}), listing, "get", status=200)
    body = {**REFERENCES[kind], "sort_order": 99, "is_active": True}
    sends(listing, "post", body)
    created = admin.post(listing, body, format="json")
    conforms(created, listing, "post", status=201)
    one = f"{listing}{created.json()['id']}/"
    sends(item, "patch", {"name": "Новое имя", "sort_order": 100, "is_active": False})
    conforms(admin.patch(one, {"name": "Новое имя", "sort_order": 100, "is_active": False}, format="json"), item, "patch", status=200)
    conforms(admin.delete(one), item, "delete", status=204)


# --- категории и запросы на категории (B-011 б) -----------------------------------------------------------------


def test_categories_crud(admin, company):
    listing = f"{API}catalog/categories/"
    item = f"{API}catalog/categories/{{id}}/"
    conforms(admin.get(listing, {"page_size": 200}), listing, "get", status=200)
    sends(listing, "post", {"name": "Кат 1", "parent": None})
    created = admin.post(listing, {"name": "Кат 1", "parent": None}, format="json")
    conforms(created, listing, "post", status=201)
    one = f"{listing}{created.json()['id']}/"
    child = admin.post(listing, {"name": "Кат 1.1", "parent": created.json()["id"]}, format="json")
    conforms(child, listing, "post", status=201)
    sends(item, "patch", {"name": "Кат 1 б", "parent": None})
    conforms(admin.patch(one, {"name": "Кат 1 б"}, format="json"), item, "patch", status=200)
    refused = admin.delete(one)
    assert refused.json() == {"detail": "CATEGORY_HAS_CHILDREN"}
    conforms(refused, item, "delete", status=400)
    conforms(admin.delete(f"{listing}{child.json()['id']}/"), item, "delete", status=204)


def test_category_requests_list_approve_reject(admin, company):
    listing = f"{API}catalog/category-requests/"
    pending = [CategoryRequest.objects.create(company=company, proposed_name=f"Нужна {i}") for i in range(3)]
    category = Category.objects.create(name="Заведена")
    response = admin.get(listing, {"status": "PENDING", "page": 1, "page_size": 200})
    conforms(response, listing, "get", status=200)
    assert response.json()["count"] == 3
    # Ответы — CategoryProposal (а не Category): те самые поля, которые читает BFF.
    assert {"proposed_name", "company_name", "requested_by_email", "resulting_category_name"} <= set(
        response.json()["results"][0]
    )
    approve = f"{API}catalog/category-requests/{{id}}/approve/"
    sends(approve, "post", {"category": category.id})
    ok = admin.post(f"{listing}{pending[0].id}/approve/", {"category": category.id}, format="json")
    conforms(ok, approve, "post", status=200)
    again = admin.post(f"{listing}{pending[0].id}/approve/", {"category": category.id}, format="json")
    assert again.json() == {"detail": "CATEGORY_REQUEST_ALREADY_REVIEWED"}
    conforms(again, approve, "post", status=400)
    reject = f"{API}catalog/category-requests/{{id}}/reject/"
    sends(reject, "post", {"reason": "Дубль"})
    conforms(admin.post(f"{listing}{pending[1].id}/reject/", {"reason": "Дубль"}, format="json"), reject, "post", status=200)
    no_reason = admin.post(f"{listing}{pending[2].id}/reject/", {}, format="json")
    assert no_reason.json() == {"detail": "REASON_REQUIRED"}
    conforms(no_reason, reject, "post", status=400)


def test_category_request_submit_by_seller(company):
    """Подача запроса продавцом: `create` и `retrieve` описаны схемой запроса-сущности, а не `Category`."""
    from rest_framework.test import APIClient

    from accounts.models import CompanyMember, CompanyRole, WorkspaceRole

    role = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20})[0]
    company_role = CompanyRole.objects.create(company=company, name="Каталог", permissions=["catalog.manage"])
    seller = CustomUser.objects.create_user(email="seller@d2-0.test", username="seller@d2-0.test", password="pw")
    CompanyMember.objects.create(
        user=seller, company=company, role=role, company_roles=[company_role], is_active=True, is_primary=True
    )
    client = APIClient()
    client.force_authenticate(seller)
    listing = f"{API}catalog/category-requests/"
    body = {"proposed_name": "Нужна категория", "justification": "Не нашли"}
    sends(listing, "post", body)
    created = client.post(listing, body, format="json")
    conforms(created, listing, "post", status=201)
    conforms(client.get(f"{listing}{created.json()['id']}/"), f"{listing}{{id}}/", "get", status=200)
    twice = client.post(listing, body, format="json")
    conforms(twice, listing, "post", status=400)


# --- платформенные настройки и курс -----------------------------------------------------------------------------


def test_system_settings_and_shared_field_refusal(admin, company):
    template = f"{API}system-settings/"
    conforms(admin.get(template), template, "get", status=200)
    sends(template, "patch", {"vat_rate": "12.00"})
    conforms(admin.patch(template, {"vat_rate": "12.00"}, format="json"), template, "patch", status=200)
    refused = admin.patch(template, {"platform_name": "X"}, format="json")
    assert refused.json()["detail"] == "SHARED_SETTING_READ_ONLY"
    conforms(refused, template, "patch", status=400)


def test_exchange_rates_current_journal_manual(admin, company):
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "sort_order": 1})
    manual = f"{API}exchange-rates/manual/"
    body = {"currency": "USD", "rate_date": datetime.date.today().isoformat(), "rate_to_uzs": "12500.00"}
    sends(manual, "post", body)
    conforms(admin.post(manual, body, format="json"), manual, "post", status=201)
    conforms(
        admin.get(f"{API}exchange-rates/current/", {"currency": "USD"}),
        f"{API}exchange-rates/current/",
        "get",
        status=200,
    )
    conforms(
        admin.get(f"{API}exchange-rates/journal/", {"currency": "USD", "limit": 20}),
        f"{API}exchange-rates/journal/",
        "get",
        status=200,
    )
    future = {**body, "rate_date": (datetime.date.today() + datetime.timedelta(days=5)).isoformat()}
    refused = admin.post(manual, future, format="json")
    assert refused.json() == {"detail": "FX_RATE_DATE_IN_FUTURE"}
    conforms(refused, manual, "post", status=400)
