"""Regression: the buyer's add-request-item path must persist the article (mpn).

Bug: buyer_add_request_item dropped `mpn` (the view never forwarded it and the
service had no parameter), so a new request line lost its article while the edit
path saved it — an inconsistency between the two endpoints. These tests lock the
field in and cover the mpn-based dedup it enables.
"""

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import Deal, DealStage, QuoteStatus
from crm.services.rfq import buyer_add_request_item


@pytest.fixture
def lookups(db):
    # Tests run with --nomigrations, so seed the codes this flow touches.
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})


@pytest.fixture
def deal(lookups):
    buyer = CustomUser.objects.create_user(
        email="add.buyer@example.com", username="add_buyer", password="pw", is_active=True
    )
    company = Company.objects.create(
        name="Add Buyer LLC", inn="7700000099", verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    # OWNER membership; can_buy defaults to True (see CompanyMember model).
    CompanyMember.objects.create(
        user=buyer, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(
        title="Add-item Deal", company=company, client=buyer, stage=DealStage.objects.get(code="DRAFT")
    )
    return deal, buyer


@pytest.mark.django_db
def test_add_request_item_persists_mpn_and_note(deal):
    deal_obj, buyer = deal
    item = buyer_add_request_item(
        buyer, deal_obj, name="Баббит Б-83", quantity=2, mpn="ART-XYZ-9", note="моё примечание"
    )
    item.refresh_from_db()
    assert item.mpn == "ART-XYZ-9"  # the bug dropped this to ""
    assert item.note == "моё примечание"
    assert item.imported_raw_name == "Баббит Б-83"
    assert item.quantity == 2


@pytest.mark.django_db
def test_add_request_item_mpn_truncated_to_column_limit(deal):
    deal_obj, buyer = deal
    item = buyer_add_request_item(buyer, deal_obj, name="x", quantity=1, mpn="A" * 200)
    item.refresh_from_db()
    assert len(item.mpn) == 120


@pytest.mark.django_db
def test_add_request_item_dedups_by_mpn(deal):
    # Same article, different display name → one line with summed quantity
    # (_line_dedup_key prefers mpn). This only works once mpn is actually stored.
    deal_obj, buyer = deal
    first = buyer_add_request_item(buyer, deal_obj, name="Болт вариант A", quantity=3, mpn="SAME-CODE")
    second = buyer_add_request_item(buyer, deal_obj, name="Болт вариант B", quantity=4, mpn="SAME-CODE")
    assert first.id == second.id
    second.refresh_from_db()
    assert second.quantity == 7


@pytest.mark.django_db
def test_cart_line_inherits_product_attributes(deal):
    """Owner-reported: a catalog line added from the cart must INHERIT the product's
    uom / MPN / ГОСТ / ТНВЭД — not arrive as name+qty only (single source of truth)."""
    from catalog.models import Product, ProductStatus
    from crm.models import QuoteItem
    from crm.services.rfq import buyer_add_request_items
    from master_data.models import UnitOfMeasure

    deal_obj, buyer = deal
    uom = UnitOfMeasure.objects.create(code="PCE", name="шт")
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "P", "sort_order": 1})[0]
    product = Product.objects.create(
        name="Автосцепка СА-3",
        status=pub,
        uom=uom,
        manufacturer_part_number="SA3-001",
        gost_drawing="ГОСТ 3475-81",
        hs_code="8607300000",
    )
    buyer_add_request_items(buyer, deal_obj, [{"product_id": product.id, "quantity": 3}])
    line = QuoteItem.objects.filter(quote__deal=deal_obj, product=product).first()
    assert line is not None
    assert line.unit == "шт" and line.unit_code == "PCE", f"uom not inherited: {line.unit!r}/{line.unit_code!r}"
    assert line.mpn == "SA3-001"
    assert line.gost_drawing == "ГОСТ 3475-81"
    assert line.hs_code == "8607300000"
    assert line.quantity == 3
