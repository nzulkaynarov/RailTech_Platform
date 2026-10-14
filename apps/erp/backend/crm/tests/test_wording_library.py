"""E4 — библиотека согласованных формулировок (spec-wording-library-e4-2026-08-01).

Playbook-канон: юрист заранее готовит именованные редакции пункта, менеджер в переговорах
по КОНКРЕТНОМУ договору выбирает из них — не сочиняя текст и не трогая шаблон компании.
Плюс закрытие дыры E3: формулировки резолвились живьём при каждом рендере, и правка профиля
после создания договора перепечатывала уже отправленный клиенту документ.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyDocumentProfile,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    WorkspaceRole,
)
from crm.models import CompanyWordingVariant, ContractStatus, Deal, DealStage, Quote, QuoteStatus
from crm.services.contracts import generate_contract_from_quote
from crm.services.document_blocks import contract_block_values
from crm.services.wording_variants import create_variant, select_contract_wording

TOTALS = {"ccy": "UZS", "total": Decimal("112.00")}


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ("DRAFT", "CONTRACT_SIGNED"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "SENT", "APPROVED"):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "PENDING_CLIENT", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


@pytest.fixture
def world(lookups):
    buyer_co = Company.objects.create(name="Buyer W", inn="B904")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_co = Company.objects.create(name="Seller W", inn="S904")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller_user = CustomUser.objects.create_user(email="s@word.test", username="s@word.test", password="x")
    CompanyMember.objects.create(
        user=seller_user,
        company=seller_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    deal = Deal.objects.create(title="W deal", company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="APPROVED"),
        prepared_by=seller_user,
        seller_company=seller_co,
        total_incl_vat=Decimal("112"),
    )
    return {"seller_co": seller_co, "seller_user": seller_user, "deal": deal, "quote": quote}


def _contract(world):
    contract, err = generate_contract_from_quote(world["quote"].id, actor=world["seller_user"])
    assert err is None, err
    return contract


@pytest.mark.django_db
def test_contract_is_born_with_frozen_wordings_and_profile_edits_do_not_leak(world):
    """Дыра E3 закрыта: правка профиля ПОСЛЕ создания не перепечатывает договор."""
    CompanyDocumentProfile.objects.create(company=world["seller_co"], contract_liability_text="Неустойка 0,05% в день.")
    contract = _contract(world)
    assert contract.wording_selections["contract_liability_text"] == "Неустойка 0,05% в день."

    profile = CompanyDocumentProfile.objects.get(company=world["seller_co"])
    profile.contract_liability_text = "Неустойка 1% — новая политика."
    profile.save(update_fields=["contract_liability_text"])

    blocks = contract_block_values(contract, [], TOTALS, "UZS", seller_profile=profile)
    assert "0,05%" in str(blocks["doc.contract_liability"])
    assert "новая политика" not in str(blocks["doc.contract_liability"])


@pytest.mark.django_db
def test_manager_selects_an_approved_variant_for_this_contract_only(world):
    """Playbook: выбор согласованного фолбэка меняет ЭТОТ договор, а не шаблон компании."""
    variant = create_variant(
        world["seller_co"],
        world["seller_user"],
        field="contract_liability_text",
        title="Неустойка 0,05%",
        text="Согласованный фолбэк: неустойка 0,05% в день, потолок 5%.",
    )
    contract = _contract(world)

    contract, err = select_contract_wording(
        contract, world["seller_user"], field="contract_liability_text", variant_id=variant.id
    )

    assert err is None
    assert "потолок 5%" in contract.wording_selections["contract_liability_text"]
    # Другой договор той же компании рождается со СТАНДАРТНОЙ редакцией.
    quote2 = Quote.objects.create(
        deal=world["deal"],
        version=2,
        status=QuoteStatus.objects.get(code="APPROVED"),
        prepared_by=world["seller_user"],
        seller_company=world["seller_co"],
        total_incl_vat=Decimal("50"),
    )
    other, err = generate_contract_from_quote(quote2.id, actor=world["seller_user"])
    assert err is None
    assert "потолок 5%" not in other.wording_selections["contract_liability_text"]


@pytest.mark.django_db
def test_selection_is_blocked_after_any_signature(world):
    contract = _contract(world)
    contract.client_signer = world["seller_user"]
    contract.save(update_fields=["client_signer"])

    _c, err = select_contract_wording(contract, world["seller_user"], field="contract_liability_text", variant_id=None)
    assert err == "CONTRACT_ALREADY_SIGNED"


@pytest.mark.django_db
def test_selection_validates_field_and_variant_ownership(world):
    contract = _contract(world)
    _c, err = select_contract_wording(contract, world["seller_user"], field="hacker_field", variant_id=None)
    assert err == "WORDING_FIELD_UNKNOWN"

    stranger_co = Company.objects.create(name="Чужая", inn="S905")
    foreign = CompanyWordingVariant.objects.create(
        company=stranger_co, field="contract_liability_text", title="Чужой", text="x"
    )
    _c, err = select_contract_wording(
        contract, world["seller_user"], field="contract_liability_text", variant_id=foreign.id
    )
    assert err == "WORDING_VARIANT_NOT_FOUND"


@pytest.mark.django_db
def test_variant_crud_is_company_scoped_via_api(world):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(world['seller_user']).access_token}")

    resp = client.post(
        "/api/v1/crm/wording-variants/",
        {"field": "contract_liability_text", "title": "Мягкая", "text": "Неустойка 0,01%."},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    resp = client.post(
        "/api/v1/crm/wording-variants/",
        {"field": "nope", "title": "X", "text": "Y"},
        format="json",
    )
    assert resp.status_code == 400 and resp.json()["detail"] == "WORDING_FIELD_UNKNOWN"

    # Чужая компания не видит вариантов продавца.
    outsider = CustomUser.objects.create_user(email="o@word.test", username="o@word.test", password="x")
    other_co = Company.objects.create(name="Другая", inn="S906")
    other_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    CompanyMember.objects.create(
        user=outsider,
        company=other_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    api2 = APIClient()
    api2.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(outsider).access_token}")
    assert api2.get("/api/v1/crm/wording-variants/").json() == []
