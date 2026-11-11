"""Бланк своей компании → EDS (P4 волны 18a): событие `letterhead.updated` при сохранении «Компания и бланки».

Публикуется в транзакции сохранения (outbox rt_bus), только для своей компании ERP; логотип — байтами по контракту
(большой растр уменьшается, SVG — `logo = null`, `unsupported`); `data` проходит схему контракта строго.
"""

import base64
import hashlib
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from integration.tests.bus_support import assert_matches_contract
from PIL import Image
from rt_bus.django.models import Outbox

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.services import update_document_profile, upload_document_profile_logo
from accounts.services.letterhead_event import LETTERHEAD_UPDATED, LOGO_MAX_BYTES, letterhead_data
from accounts.testing import grant_head, make_own_company


def _owner(company, email):
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_primary=True, is_active=True)
    grant_head(user, company)
    return user


def _letterheads():
    return [row.envelope for row in Outbox.objects.filter(type=LETTERHEAD_UPDATED).order_by("created_at", "id")]


def _png(width, height, noise=False):
    image = Image.new("RGB", (width, height), "white")
    if noise:
        image = Image.effect_noise((width, height), 100).convert("RGB")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def own(db):
    company = Company.objects.create(name="РемПуть")
    make_own_company(company)
    return company, _owner(company, "head@own.test")


@pytest.mark.django_db
def test_saving_requisites_publishes_full_letterhead_snapshot(own):
    company, head = own
    profile, error = update_document_profile(
        head,
        company,
        {
            "legal_name": "ООО «РемПуть»",
            "inn": "305123456",
            "signatory_name": "Каримов А. А.",
            "signatory_position": "Директор",
            "accent_color": "#15294d",
        },
    )
    assert error is None and profile is not None
    [envelope] = _letterheads()
    assert_matches_contract(envelope)
    head_data = envelope["data"]["letterhead"]
    assert envelope["data"]["erp_company_id"] == company.id and envelope["subject"] == f"company/{company.id}"
    # Одни реквизиты (решение 2026-11-11): имя и ИНН — из карточки компании; профиль — только если в карточке пусто.
    assert (head_data["company_name"], head_data["inn"], head_data["signatory_name"], head_data["logo"]) == (
        "РемПуть",
        "305123456",
        "Каримов А. А.",
        None,
    )
    # «Сохранить» без правок досылает бланк ещё раз (данные до P4)
    update_document_profile(head, company, {})
    assert len(_letterheads()) == 2


@pytest.mark.django_db
def test_other_company_profile_does_not_reach_eds(own):
    other = Company.objects.create(name="Клиент")
    other_head = _owner(other, "head@other.test")
    update_document_profile(other_head, other, {"legal_name": "ООО «Клиент»"})
    assert _letterheads() == []


@pytest.mark.django_db
def test_logo_goes_as_bytes_and_large_one_is_downscaled(own, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    company, head = own
    small = _png(120, 40)
    upload_document_profile_logo(head, company, SimpleUploadedFile("logo.png", small, content_type="image/png"))
    [envelope] = _letterheads()
    assert_matches_contract(envelope)
    logo = envelope["data"]["letterhead"]["logo"]
    assert base64.b64decode(logo["data_base64"]) == small and logo["sha256"] == hashlib.sha256(small).hexdigest()

    big = _png(2400, 900, noise=True)
    profile, _ = upload_document_profile_logo(
        head, company, SimpleUploadedFile("big.png", big, content_type="image/png")
    )
    data = letterhead_data(company, profile, head)["letterhead"]
    raw = base64.b64decode(data["logo"]["data_base64"])
    assert len(raw) <= LOGO_MAX_BYTES and data["logo"]["size"] == len(raw)
    with Image.open(io.BytesIO(raw)) as fitted:
        assert fitted.width <= 1200 and fitted.height <= 400

    profile.show_logo = False
    hidden = letterhead_data(company, profile, head)["letterhead"]
    assert hidden["logo"] is None and hidden["logo_omitted"] == "hidden"


@pytest.mark.django_db
def test_company_requisites_reach_eds_without_saving_the_letterhead(own):
    """Правка реквизитов в карточке компании сама обновляет бланк EDS — с ИНН, адресом и банком из карточки."""
    company, _head = own
    before = len(_letterheads())
    company.inn = "305999888"
    company.legal_address = "Ташкент, ул. Демо, 1"
    company.bank_account = "20208000900001234567"
    company.mfo = "00873"
    company.save()
    envelopes = _letterheads()
    assert len(envelopes) == before + 1
    assert_matches_contract(envelopes[-1])
    head_data = envelopes[-1]["data"]["letterhead"]
    assert (head_data["inn"], head_data["legal_address"]) == ("305999888", "Ташкент, ул. Демо, 1")
    assert head_data["bank_details"] == "р/с: 20208000900001234567, МФО: 00873"


@pytest.mark.django_db
def test_saving_unrelated_company_fields_or_another_company_does_not_publish(own):
    company, _head = own
    before = len(_letterheads())
    company.save(update_fields=["phone"])
    other = Company.objects.create(name="Клиент", inn="301111111")
    other.save()
    assert len(_letterheads()) == before
