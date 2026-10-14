"""E1 structured-timeline events for the deal lifecycle (``crm/services/deals.py``), the КП
lifecycle wrapper (``crm/services/quotes.py``), the expiry Beat task (``crm/tasks.py``) and the
public lead endpoint (``crm/views/leads.py``).

Each producer must now write a machine ``event_code`` + interpolation ``event_params`` next to the
legacy RU ``action``/``detail`` (kept as fallback), so the client can localize the timeline by the
viewer's locale. These tests exercise the real producers and assert code + params land on the row.
"""

import pytest
from django.utils import timezone


@pytest.fixture
def lookups(db):
    from accounts.models import CompanyType, WorkspaceRole
    from crm.models import DealStage, QuoteStatus

    for code in ["DRAFT", "RFQ_OPEN"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["CLIENT", "SUPPLIER"]:
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 1})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, rank in [("DRAFT", 1), ("SENT", 50), ("EXPIRED", 60)]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": rank})


def _company(name, type_code):
    from accounts.models import Company, CompanyType

    company = Company.objects.create(name=name)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, **flags):
    from accounts.models import CompanyMember, CustomUser, WorkspaceRole

    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        **flags,
    )
    return user


# ── deals.py ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_deal_created_writes_event_code_and_params(lookups):
    from crm.models import ActivityLog, Deal, DealStage
    from crm.services.deals import register_new_deal

    buyer_company = _company("Buyer Co", "CLIENT")
    actor = _member(buyer_company, "buyer_create@t.test", can_buy=True)
    deal = Deal.objects.create(title="New deal", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))

    register_new_deal(deal, actor)

    log = ActivityLog.objects.filter(deal=deal, event_code="deal.created").get()
    assert log.event_params == {
        "actor_email": actor.email,
        "deal_id": deal.id,
        "company_name": buyer_company.name,
    }


# ── quotes.py (via the _log_quote wrapper + direct re-match create) ───────────────────────────


@pytest.mark.django_db
def test_log_quote_threads_event_code_and_params(lookups):
    from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
    from crm.services.quotes import _log_quote

    buyer_company = _company("Buyer Co", "CLIENT")
    actor = _member(buyer_company, "seller_send@t.test", can_sell=True)
    deal = Deal.objects.create(title="Q", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(deal=deal, version=2, status=QuoteStatus.objects.get(code="DRAFT"))

    _log_quote(
        quote,
        actor,
        "КП отправлено клиенту",
        f"КП v{quote.version} ({quote.number})",
        event_code="quote.sent",
        event_params={"version": quote.version, "number": quote.number},
    )

    log = ActivityLog.objects.filter(deal=deal, event_code="quote.sent").get()
    assert log.event_params == {"version": 2, "number": quote.number}
    # legacy fallback preserved
    assert log.action == "КП отправлено клиенту"


@pytest.mark.django_db
def test_item_rematched_writes_event_code_and_params(lookups):
    from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteItem, QuoteStatus
    from crm.services.quotes import reassign_quote_item_product

    buyer_company = _company("Buyer Co", "CLIENT")
    actor = _member(buyer_company, "rematcher@t.test", can_sell=True)
    deal = Deal.objects.create(title="Q", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    item = QuoteItem.objects.create(quote=quote, imported_raw_name="Рельс Р65", quantity=1)

    # Clearing the match (product_id=None) is the light path that still logs the event.
    updated, err = reassign_quote_item_product(item.id, actor, None)
    assert err is None, err

    log = ActivityLog.objects.filter(event_code="quote.item_rematched", entity_id=quote.id).get()
    assert log.event_params == {"item_id": item.id, "product_id": None}


# ── tasks.py (expire_stale_quotes Beat task) ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_quote_expired_writes_event_code_and_params(lookups):
    from datetime import timedelta

    from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
    from crm.tasks import expire_stale_quotes

    buyer_company = _company("Buyer Co", "CLIENT")
    deal = Deal.objects.create(title="Q", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))
    yesterday = timezone.localdate() - timedelta(days=1)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        valid_until=yesterday,
    )

    expire_stale_quotes()

    log = ActivityLog.objects.filter(deal_id=deal.id, event_code="quote.expired").get()
    assert log.event_params == {
        "quote_id": quote.id,
        "version": quote.version,
        "deal_id": deal.id,
        "valid_until": str(yesterday),
    }
