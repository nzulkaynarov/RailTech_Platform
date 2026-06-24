"""DB-backed tests for QuoteCharge (КП-level UBL document AllowanceCharge).

Guards that document-level charges flow into the total BEFORE VAT:
    tax_exclusive = Σ(line final_price × qty) + Σ(charge − allowance)
    vat_amount    = tax_exclusive × vat_rate
    total_incl_vat= tax_exclusive + vat_amount
The VAT rate comes from Quote.vat_rate (DB), never a hardcoded 0.12.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyType, CustomUser, VerificationStatus
from crm.models import (
    ChargeType,
    Deal,
    DealStage,
    Quote,
    QuoteCharge,
    QuoteItem,
    QuoteStatus,
)
from master_data.models import Country


@pytest.fixture
def quote(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    vs = VerificationStatus.objects.get_or_create(
        code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30}
    )[0]
    uz = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})[0]

    user = CustomUser.objects.create_user(
        email="charge.buyer@example.com", username="charge_buyer", password="pw", is_active=True
    )
    company = Company.objects.create(name="Charge LLC", inn="9900000099", verification_status=vs)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    deal = Deal.objects.create(
        title="Charge Deal", company=company, client=user, stage=DealStage.objects.get(code="DRAFT")
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        tax_country=uz,
        vat_rate=Decimal("12.00"),
    )
    # One line: base 100, no logistics/customs/margin → final 100.00, qty 1.
    QuoteItem.objects.create(quote=quote, frozen_base_price=Decimal("100.00"), quantity=1)
    quote.refresh_from_db()
    return quote


@pytest.mark.django_db
def test_baseline_without_charges(quote):
    """No charges → subtotal=100, charges_total=0, vat=12, total=112."""
    assert quote.subtotal_excl_vat == Decimal("100.00")
    assert quote.charges_total == Decimal("0.00")
    assert quote.vat_amount == Decimal("12.00")
    assert quote.total_incl_vat == Decimal("112.00")


@pytest.mark.django_db
def test_header_charges_add_before_vat(quote):
    """Freight +50, rent +30 → charges 80; tax_excl 180; vat 21.60; total 201.60."""
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    rent = ChargeType.objects.create(code="RENT", name="Аренда склада")
    QuoteCharge.objects.create(quote=quote, charge_type=freight, amount=Decimal("50.00"))
    QuoteCharge.objects.create(quote=quote, charge_type=rent, amount=Decimal("30.00"))
    quote.refresh_from_db()

    assert quote.subtotal_excl_vat == Decimal("100.00")  # lines only, unchanged
    assert quote.charges_total == Decimal("80.00")
    assert quote.vat_amount == Decimal("21.60")  # 180 * 12%
    assert quote.total_incl_vat == Decimal("201.60")


@pytest.mark.django_db
def test_allowance_is_subtracted(quote):
    """Charge +50 and allowance −10 → net charges 40; tax_excl 140; total 156.80."""
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    discount = ChargeType.objects.create(code="DISCOUNT", name="Скидка")
    QuoteCharge.objects.create(quote=quote, charge_type=freight, amount=Decimal("50.00"))
    QuoteCharge.objects.create(
        quote=quote, charge_type=discount, amount=Decimal("10.00"), is_deduction=True
    )
    quote.refresh_from_db()

    assert quote.charges_total == Decimal("40.00")
    assert quote.vat_amount == Decimal("16.80")  # 140 * 12%
    assert quote.total_incl_vat == Decimal("156.80")


@pytest.mark.django_db
def test_percent_discount_on_whole_quote(quote):
    """−5% on subtotal 100 → charges −5; tax_excl 95; vat 11.40; total 106.40."""
    discount = ChargeType.objects.create(code="DISCOUNT", name="Скидка")
    QuoteCharge.objects.create(
        quote=quote, charge_type=discount, rate_percent=Decimal("5"), is_deduction=True
    )
    quote.refresh_from_db()

    assert quote.charges_total == Decimal("-5.00")
    assert quote.vat_amount == Decimal("11.40")
    assert quote.total_incl_vat == Decimal("106.40")


@pytest.mark.django_db
def test_percent_takes_priority_over_amount(quote):
    """rate_percent set → amount is ignored (10% of 100 = 10, not the 999 amount)."""
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    QuoteCharge.objects.create(
        quote=quote, charge_type=freight, amount=Decimal("999.00"), rate_percent=Decimal("10")
    )
    quote.refresh_from_db()

    assert quote.charges_total == Decimal("10.00")  # 10% of subtotal 100, amount ignored


# ─── ТНВЭД inheritance from the product card ────────────────────────────────


@pytest.mark.django_db
def test_hs_code_inherited_from_product_on_assign(quote):
    from catalog.models import Product
    from crm.services.quotes import reassign_quote_item_product

    product = Product.objects.create(name="Тормозная колодка", hs_code="8607300000")
    item = quote.items.first()
    assert item.hs_code == ""

    _result, err = reassign_quote_item_product(item.id, quote.deal.client, product_id=product.id)
    assert err is None
    item.refresh_from_db()
    assert item.hs_code == "8607300000"


@pytest.mark.django_db
def test_manual_hs_code_not_overwritten_on_assign(quote):
    """ВЭД per-line override wins — assigning a product must not clobber it."""
    from catalog.models import Product
    from crm.services.quotes import reassign_quote_item_product

    product = Product.objects.create(name="Деталь", hs_code="8607300000")
    item = quote.items.first()
    item.hs_code = "9999999999"
    item.save(update_fields=["hs_code"])

    reassign_quote_item_product(item.id, quote.deal.client, product_id=product.id)
    item.refresh_from_db()
    assert item.hs_code == "9999999999"


# ─── Incoterm charge templates (auto-apply) ─────────────────────────────────


@pytest.mark.django_db
def test_charge_template_auto_applies_and_is_idempotent(quote):
    from crm.models import ChargeTemplate
    from crm.services.charges import apply_charge_template_to_quote
    from master_data.models import DeliveryBasis

    ddp = DeliveryBasis.objects.create(code="DDP", name="DDP", seller_pays_import=True)
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    customs = ChargeType.objects.create(code="CUSTOMS", name="Таможня")
    ChargeTemplate.objects.create(delivery_basis=ddp, charge_type=freight, default_amount=Decimal("500"))
    ChargeTemplate.objects.create(delivery_basis=ddp, charge_type=customs, default_rate_percent=Decimal("5"))

    quote.delivery_basis = ddp
    quote.save(update_fields=["delivery_basis"])

    created = apply_charge_template_to_quote(quote)
    assert created == 2
    assert quote.charges.filter(from_template=True).count() == 2
    # Re-applying the same basis must not duplicate rows.
    assert apply_charge_template_to_quote(quote) == 0
    assert quote.charges.count() == 2


@pytest.mark.django_db
def test_template_does_not_clobber_manual_charge(quote):
    """A manually-added charge of the same type blocks the template duplicate."""
    from crm.models import ChargeTemplate, QuoteCharge
    from crm.services.charges import apply_charge_template_to_quote
    from master_data.models import DeliveryBasis

    cif = DeliveryBasis.objects.create(code="CIF", name="CIF")
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    ChargeTemplate.objects.create(delivery_basis=cif, charge_type=freight, default_amount=Decimal("100"))
    # Seller already entered a freight charge by hand.
    QuoteCharge.objects.create(quote=quote, charge_type=freight, amount=Decimal("777"))

    quote.delivery_basis = cif
    quote.save(update_fields=["delivery_basis"])
    assert apply_charge_template_to_quote(quote) == 0
    assert quote.charges.get(charge_type=freight).amount == Decimal("777")


# ─── Per-company charge templates (scope + global fallback) ─────────────────


def _seller_user_with_supplier_company(inn):
    from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole

    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    co = Company.objects.create(name=f"Seller {inn}", inn=inn)
    co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=f"s{inn}@s.test", username=f"s{inn}@s.test", password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=co, role=owner_role, is_active=True, can_sell=True)
    return user, co


@pytest.mark.django_db
def test_company_templates_override_global(quote):
    from crm.models import ChargeTemplate
    from crm.services.charges import apply_charge_template_to_quote
    from master_data.models import DeliveryBasis

    ddp = DeliveryBasis.objects.create(code="DDP", name="DDP")
    rent = ChargeType.objects.create(code="RENT", name="Аренда")
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    ChargeTemplate.objects.create(company=None, delivery_basis=ddp, charge_type=freight)  # global default

    seller, co = _seller_user_with_supplier_company("7777777777")
    ChargeTemplate.objects.create(company=co, delivery_basis=ddp, charge_type=rent)  # company's own

    quote.delivery_basis = ddp
    quote.save(update_fields=["delivery_basis"])
    created = apply_charge_template_to_quote(quote, seller)
    assert created == 1
    assert quote.charges.get(from_template=True).charge_type.code == "RENT"


@pytest.mark.django_db
def test_falls_back_to_global_when_company_has_none(quote):
    from crm.models import ChargeTemplate
    from crm.services.charges import apply_charge_template_to_quote
    from master_data.models import DeliveryBasis

    ddp = DeliveryBasis.objects.create(code="DDP", name="DDP")
    freight = ChargeType.objects.create(code="FREIGHT", name="Фрахт")
    ChargeTemplate.objects.create(company=None, delivery_basis=ddp, charge_type=freight)  # global only

    seller, _co = _seller_user_with_supplier_company("6666666666")

    quote.delivery_basis = ddp
    quote.save(update_fields=["delivery_basis"])
    created = apply_charge_template_to_quote(quote, seller)
    assert created == 1
    assert quote.charges.get(from_template=True).charge_type.code == "FREIGHT"
