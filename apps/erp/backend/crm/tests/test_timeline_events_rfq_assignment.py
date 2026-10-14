"""E1 structured-timeline events for the buyer RFQ path (``crm/services/rfq.py``) and the
seller work-queue (``crm/services/assignment.py``).

Each producer must now write a machine ``event_code`` + interpolation ``event_params`` next to the
legacy RU ``action``/``detail`` (kept as fallback). These tests exercise the real services and assert
the code + params land on the ActivityLog row so the client can localize the timeline by viewer locale.
"""

import pytest


@pytest.fixture
def rfq_lookups(db):
    from accounts.models import CompanyType, WorkspaceRole
    from crm.models import DealStage, QuoteStatus

    for code in ["DRAFT", "RFQ_OPEN"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["CLIENT", "SUPPLIER"]:
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 1})
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 50})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 1})


def _make_company(name, type_code):
    from accounts.models import Company, CompanyType

    company = Company.objects.create(
        name=name,
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _make_member(company, email, *, can_buy=False, can_sell=False):
    from accounts.models import CompanyMember, CustomUser, WorkspaceRole

    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        is_active=True,
        can_buy=can_buy,
        can_sell=can_sell,
        is_primary=True,
    )
    return user


# ── rfq.py ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_item_added_writes_event_code_and_params(rfq_lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.rfq import buyer_add_request_item

    buyer_company = _make_company("Buyer Co", "CLIENT")
    buyer = _make_member(buyer_company, "buyer_add@t.test", can_buy=True)
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))

    item = buyer_add_request_item(buyer, deal, name="Рельс Р65", quantity=3)

    log = ActivityLog.objects.filter(deal=deal, event_code="deal.item_added").get()
    assert log.event_params == {"deal_id": deal.id, "name": "Рельс Р65", "quantity": item.quantity}


@pytest.mark.django_db
def test_items_added_bulk_writes_event_code_and_count(rfq_lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.rfq import buyer_add_request_items

    buyer_company = _make_company("Buyer Co", "CLIENT")
    buyer = _make_member(buyer_company, "buyer_bulk@t.test", can_buy=True)
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))

    buyer_add_request_items(buyer, deal, [{"name": "Рельс Р65", "quantity": 2}, {"name": "Накладка", "quantity": 1}])

    log = ActivityLog.objects.filter(deal=deal, event_code="deal.items_added_bulk").get()
    assert log.event_params == {"deal_id": deal.id, "count": 2}


@pytest.mark.django_db
def test_item_removed_writes_event_code_and_item_id(rfq_lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.rfq import buyer_add_request_item, buyer_remove_request_item

    buyer_company = _make_company("Buyer Co", "CLIENT")
    buyer = _make_member(buyer_company, "buyer_rm@t.test", can_buy=True)
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))
    item = buyer_add_request_item(buyer, deal, name="Рельс Р65", quantity=1)
    item_id = item.id

    buyer_remove_request_item(buyer, item)

    log = ActivityLog.objects.filter(deal=deal, event_code="deal.item_removed").get()
    assert log.event_params == {"deal_id": deal.id, "item_id": item_id}


@pytest.mark.django_db
def test_submitted_writes_event_code_and_line_count(rfq_lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.rfq import buyer_add_request_item, submit_request

    buyer_company = _make_company("Buyer Co", "CLIENT")
    buyer = _make_member(buyer_company, "buyer_submit@t.test", can_buy=True)
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))
    buyer_add_request_item(buyer, deal, name="Рельс Р65", quantity=3)
    buyer_add_request_item(buyer, deal, name="Накладка 2Р65", quantity=1)

    submit_request(buyer, deal)

    log = ActivityLog.objects.filter(deal=deal, event_code="deal.submitted").get()
    assert log.event_params == {"deal_id": deal.id, "count": 2}


# ── assignment.py ───────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_claim_and_release_write_event_codes(rfq_lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.assignment import claim_deal, release_deal

    buyer_company = _make_company("Buyer Co", "CLIENT")
    seller_company = _make_company("Seller Co", "SUPPLIER")
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="RFQ_OPEN"))
    seller = _make_member(seller_company, "seller_claim@s.test", can_sell=True)

    _, err = claim_deal(deal.id, seller)
    assert err is None
    claim_log = ActivityLog.objects.filter(deal_id=deal.id, event_code="deal.claimed").get()
    assert claim_log.event_params == {"actor_email": seller.email, "deal_id": deal.id}

    _, err2 = release_deal(deal.id, seller)
    assert err2 is None
    release_log = ActivityLog.objects.filter(deal_id=deal.id, event_code="deal.released").get()
    assert release_log.event_params == {"actor_email": seller.email, "deal_id": deal.id}


@pytest.mark.django_db
def test_assign_writes_event_code_and_assignee(rfq_lookups):
    from accounts.models import CompanyRole
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.assignment import assign_deal

    buyer_company = _make_company("Buyer Co", "CLIENT")
    seller_company = _make_company("Seller Co", "SUPPLIER")
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="RFQ_OPEN"))

    # Staff member with deal.assign (M1-ERP-05) assigns the deal to a teammate.
    admin_role = CompanyRole.objects.create(company=seller_company, name="Admin", permissions=["deal.assign"])
    admin = _make_member(seller_company, "seller_admin@s.test", can_sell=True)
    admin.memberships.get(company=seller_company).company_roles.add(admin_role)
    assignee = _make_member(seller_company, "seller_assignee@s.test", can_sell=True)

    _, err = assign_deal(deal.id, admin, assignee.id)
    assert err is None, err
    log = ActivityLog.objects.filter(deal_id=deal.id, event_code="deal.assigned").get()
    assert log.event_params == {"actor_email": admin.email, "deal_id": deal.id, "assignee_email": assignee.email}
