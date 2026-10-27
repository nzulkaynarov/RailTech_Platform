"""D2-0 (B-011): операции `/api/v1`, которые зовёт BFF Платформы для «Admin · Компания», отвечают как обещает выгрузка.

Схема — из кода (`core/tests/openapi_internal.py`), тела запросов — те, что шлёт BFF (`apps/platform/bff/app/api/admin_company.py`
и `schemas_company.py`), ответы — живые. Расхождение «код ↔ описание» — падение теста: либо поправить `extend_schema`
операции, либо (если поменялось поведение) договориться через ADR. Поведение API этот файл не меняет.
"""

import pytest

from core.tests.openapi_fixtures import API, conforms, sends
from core.tests.openapi_internal import request_fields_missing
from master_data.models import Country, Currency, DeliveryBasis

pytest_plugins = ["core.tests.openapi_fixtures"]  # фикстуры `admin` и `company`
pytestmark = pytest.mark.django_db

# --- настройки компании (B-011 а) --------------------------------------------------------------------------------


def test_company_settings_patch_describes_codes_bff_sends(admin, company):
    template = f"{API}accounts/companies/{{id}}/settings/"
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "sort_order": 1})
    DeliveryBasis.objects.get_or_create(code="FCA", defaults={"name": "FCA", "sort_order": 1})
    # Все поля, которые `QuoteDefaultsUpdate` BFF может отправить, и `doc_number_prefix` (нумерация).
    body = {
        "default_cost_currency": "USD",
        "default_delivery_basis": "FCA",
        "default_vat_rate": "12.00",
        "default_margin_percent": "15.50",
        "min_margin_percent": "5.00",
        "target_margin_percent": "20.00",
        "default_offer_validity_days": 30,
        "default_payment_terms": "100% предоплата",
        "default_warranty_months": 12,
        "catalog_price_visibility": "cabinet",
        "catalog_publish_threshold": 70,
        "fx_rate_max_age_days": 7,
        "doc_number_prefix": "D20",
    }
    sends(template, "patch", body)
    response = admin.patch(f"{API}accounts/companies/{company.id}/settings/", body, format="json")
    conforms(response, template, "patch", status=200)
    assert response.json()["default_cost_currency_code"] == "USD"
    conforms(admin.get(f"{API}accounts/companies/{company.id}/settings/"), template, "get", status=200)


def test_payment_terms_days_is_read_only_in_settings_patch(admin, company):
    """BFF шлёт `payment_terms_days`, а PATCH его не принимает: схема честно держит поле только в ответе (Q-D20-1)."""
    template = f"{API}accounts/companies/{{id}}/settings/"
    assert request_fields_missing(template, "patch", {"payment_terms_days": 30}) == ["payment_terms_days"]
    response = admin.patch(f"{API}accounts/companies/{company.id}/settings/", {"payment_terms_days": 30}, format="json")
    conforms(response, template, "patch", status=200)
    assert response.json()["payment_terms_days"] is None  # молча проигнорировано сервисом, как и описано


def test_company_settings_patch_refusal_is_described(admin, company):
    template = f"{API}accounts/companies/{{id}}/settings/"
    response = admin.patch(
        f"{API}accounts/companies/{company.id}/settings/", {"default_cost_currency": "XXX"}, format="json"
    )
    assert response.json() == {"detail": "BAD_CURRENCY"}
    conforms(response, template, "patch", status=400)


# --- профиль компании, бланк, логотип ---------------------------------------------------------------------------


COMPANY_FIELDS = ("name", "inn", "bank_account", "mfo", "legal_address", "phone", "contact_person", "website", "email")


def test_company_profile_round_trip(admin, company):
    template = f"{API}accounts/companies/{{id}}/"
    url = f"{API}accounts/companies/{company.id}/"
    conforms(admin.get(url), template, "get", status=200)
    country = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 1})[0]
    body = {
        "name": "ООО «Контракт»",
        "inn": "300000099",
        "bank_account": "20208000",
        "mfo": "00014",
        "legal_address": "Ташкент",
        "phone": "+998900000000",
        "contact_person": "Иванов",
        "website": "https://example.test",
        "email": "info@example.test",
        "country": country.id,
        "has_iso9001": True,
    }
    sends(template, "patch", body)
    conforms(admin.patch(url, body, format="json"), template, "patch", status=200)


def test_document_profile_round_trip_and_preview(admin, company):
    template = f"{API}accounts/companies/{{id}}/document-profile/"
    url = f"{API}accounts/companies/{company.id}/document-profile/"
    conforms(admin.get(url), template, "get", status=200)
    body = {
        "legal_name": "ООО «Контракт»",
        "inn": "300000099",
        "legal_address": "Ташкент",
        "bank_details": "р/с 2020",
        "signatory_name": "Иванов",
        "signatory_position": "Директор",
        "footer_text": "Подвал",
        "accent_color": "#112233",
        "secondary_color": "#445566",
        "cover_letter_text": "Письмо",
        "contract_acceptance_text": "a",
        "contract_liability_text": "b",
        "contract_extra_terms_text": "c",
        "act_closing_text": "d",
        "layout_preset": "boxed",
        "font_family": "serif",
        "show_cover_letter": True,
        "show_bank_in_header": False,
        "use_company_defaults": False,
        "show_logo": True,
        "show_lead_time": True,
        "show_fx_note": False,
    }
    sends(template, "patch", body)
    conforms(admin.patch(url, body, format="json"), template, "patch", status=200)
    refused = admin.patch(url, {"accent_color": "red;x"}, format="json")
    conforms(refused, template, "patch", status=400)

    preview = f"{API}accounts/companies/{{id}}/document-profile/preview/"
    sends(preview, "post", {"doc_type": "KP", "draft": {"accent_color": "#000000"}})
    response = admin.post(f"{url}preview/", {"doc_type": "KP", "draft": {"accent_color": "#000000"}}, format="json")
    conforms(response, preview, "post", status=200)
    conforms(admin.post(f"{url}preview/", {"doc_type": "NOPE"}, format="json"), preview, "post", status=400)


def test_document_profile_service_whitelist_is_in_request_schema():
    """Что сервис пишет в профиль — описано схемой запроса (иначе клиент не знает, что поле принимается)."""
    from accounts.services import document_profile as service

    described = request_fields_missing(
        f"{API}accounts/companies/{{id}}/document-profile/",
        "patch",
        dict.fromkeys(
            [*service._EDITABLE_FIELDS, *service._EDITABLE_CHOICE_FIELDS, *service._EDITABLE_BOOL_FIELDS], None
        ),
    )
    assert not described, described


# Минимальный PNG 1×1 (сигнатура и IHDR/IDAT/IEND): проходит проверку содержимого загрузок (`core/validators.py`).
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6364f8ffff3f0005fe02fea7"
    "35816a0000000049454e44ae426082"
)


def test_logo_uploads_return_the_documented_objects(admin, company, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = str(tmp_path)
    logo = SimpleUploadedFile("logo.png", PNG_1X1, content_type="image/png")
    template = f"{API}accounts/companies/{{id}}/upload-logo/"
    response = admin.post(f"{API}accounts/companies/{company.id}/upload-logo/", {"logo": logo}, format="multipart")
    conforms(response, template, "post", status=200)
    brand = SimpleUploadedFile("brand.png", PNG_1X1, content_type="image/png")
    template = f"{API}accounts/companies/{{id}}/document-profile/upload-logo/"
    url = f"{API}accounts/companies/{company.id}/document-profile/upload-logo/"
    conforms(admin.post(url, {"logo": brand}, format="multipart"), template, "post", status=200)


def test_company_logo_upload_refusals_are_described(admin, company):
    from django.core.files.uploadedfile import SimpleUploadedFile

    template = f"{API}accounts/companies/{{id}}/upload-logo/"
    response = admin.post(f"{API}accounts/companies/{company.id}/upload-logo/", {}, format="multipart")
    assert response.json() == {"detail": "NO_FILE_PROVIDED"}
    conforms(response, template, "post", status=400)
    bad = SimpleUploadedFile("logo.png", b"not-an-image", content_type="image/png")
    response = admin.post(f"{API}accounts/companies/{company.id}/upload-logo/", {"logo": bad}, format="multipart")
    conforms(response, template, "post", status=400)
    deleted = admin.delete(f"{API}accounts/companies/{company.id}/delete-logo/")
    conforms(deleted, f"{API}accounts/companies/{{id}}/delete-logo/", "delete", status=204)


# --- первый запуск и профиль сотрудника -------------------------------------------------------------------------


def test_setup_status_and_me(admin, company):
    status = admin.get(f"{API}setup/status/")
    conforms(status, f"{API}setup/status/", "get", status=200)
    assert status.json()["own_company_id"] == company.id
    conforms(admin.get(f"{API}accounts/me/"), f"{API}accounts/me/", "get", status=200)
