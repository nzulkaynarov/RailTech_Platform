"""Service tests for the КП internal approval chain (документооборот).

DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND → (send_to_client).
Each step is gated by the actor's WorkspaceRole inside the company that owns the
quote (the preparer's company); OWNER may act on any step.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.quotes import QuoteLifecycleService as QLS
from master_data.models import Country

pytestmark = pytest.mark.django_db

QUOTE_STATUSES = [
    "DRAFT",
    "PENDING_TRADE_REVIEW",
    "PENDING_APPROVAL",
    "READY_TO_SEND",
    "SENT",
    "APPROVED",
    "REJECTED",
]
CHAIN_ROLES = ["OWNER", "SALES_MANAGER", "FOREIGN_TRADE_SPECIALIST", "DIRECTOR", "MEMBER"]


@pytest.fixture
def lookups(db):
    for code in QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in CHAIN_ROLES:
        WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})


def _member(company, role_code, suffix):
    user = CustomUser.objects.create_user(
        email=f"{role_code.lower()}{suffix}@seller.test",
        username=f"{role_code.lower()}{suffix}",
        password="pw",
        is_active=True,
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=role_code),
        is_primary=True,
        is_active=True,
    )
    return user


@pytest.fixture
def seller(lookups):
    """Seller company with one member per chain role + an operational subscription
    (send-to-client / contract / act are gated behind it — ADR-0002 / F0.2)."""
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import SupplierSubscription

    company = Company.objects.create(name="Seller LLC", inn="7700000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    SupplierSubscription.objects.create(
        company=company, plan="PREMIUM", status="ACTIVE",
        valid_until=timezone.now().date() + timedelta(days=365),
    )
    users = {code: _member(company, code, "1") for code in CHAIN_ROLES}
    return {"company": company, "users": users}


@pytest.fixture
def client_co(lookups):
    company = Company.objects.create(
        name="Client LLC", inn="6600000001", verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


@pytest.fixture
def deal(seller, client_co):
    return Deal.objects.create(
        title="Chain Deal",
        company=client_co,
        manager=seller["users"]["SALES_MANAGER"],
        stage=DealStage.objects.get(code="DRAFT"),
    )


def _quote(deal, prepared_by, status_code="DRAFT"):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code=status_code),
        prepared_by=prepared_by,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


def _status(quote):
    quote.refresh_from_db()
    return quote.status.code


def test_happy_path_chain(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])

    _, err = QLS.submit_for_review(quote.id, users["SALES_MANAGER"])
    assert err is None and _status(quote) == "PENDING_TRADE_REVIEW"

    _, err = QLS.confirm_trade_review(quote.id, users["FOREIGN_TRADE_SPECIALIST"])
    assert err is None and _status(quote) == "PENDING_APPROVAL"

    _, err = QLS.director_approve(quote.id, users["DIRECTOR"])
    assert err is None and _status(quote) == "READY_TO_SEND"


def test_wrong_role_is_refused(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])

    # ВЭД cannot submit (sales-only step)
    _, err = QLS.submit_for_review(quote.id, users["FOREIGN_TRADE_SPECIALIST"])
    assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "DRAFT"

    QLS.submit_for_review(quote.id, users["SALES_MANAGER"])
    QLS.confirm_trade_review(quote.id, users["FOREIGN_TRADE_SPECIALIST"])
    # Sales cannot do the director's approval
    _, err = QLS.director_approve(quote.id, users["SALES_MANAGER"])
    assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "PENDING_APPROVAL"


def test_owner_can_act_on_any_step(seller, deal):
    owner = seller["users"]["OWNER"]
    quote = _quote(deal, prepared_by=seller["users"]["SALES_MANAGER"])
    assert QLS.submit_for_review(quote.id, owner)[1] is None
    assert QLS.confirm_trade_review(quote.id, owner)[1] is None
    assert QLS.director_approve(quote.id, owner)[1] is None
    assert _status(quote) == "READY_TO_SEND"


def test_member_without_role_is_refused(seller, deal):
    member = seller["users"]["MEMBER"]
    quote = _quote(deal, prepared_by=seller["users"]["SALES_MANAGER"])
    _, err = QLS.submit_for_review(quote.id, member)
    assert err == "ROLE_NOT_PERMITTED"


def test_trade_review_skipped_when_no_ved_member(client_co, lookups):
    company = Company.objects.create(name="No-VED LLC", inn="7700000002")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    sales = _member(company, "SALES_MANAGER", "2")
    deal = Deal.objects.create(title="D2", company=client_co, manager=sales, stage=DealStage.objects.get(code="DRAFT"))
    quote = _quote(deal, prepared_by=sales)

    _, err = QLS.submit_for_review(quote.id, sales)
    # No ВЭД in the company → jump straight to director approval.
    assert err is None and _status(quote) == "PENDING_APPROVAL"


def test_send_back_returns_to_draft(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])
    QLS.submit_for_review(quote.id, users["SALES_MANAGER"])

    _, err = QLS.send_back(quote.id, users["FOREIGN_TRADE_SPECIALIST"], reason="скорректировать цены")
    assert err is None and _status(quote) == "DRAFT"


def test_send_to_client_blocked_until_ready(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])
    # A DRAFT КП may not be sent — it must pass the approval chain first.
    with pytest.raises(ValueError):
        QLS.send_to_client(quote.id, users["SALES_MANAGER"])


# ─── DRF endpoint tests ─────────────────────────────────────────────────────


def _api(user):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def test_submit_for_review_endpoint(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])
    resp = _api(users["SALES_MANAGER"]).post(f"/api/v1/crm/quotes/{quote.id}/submit-for-review/")
    assert resp.status_code == 200
    assert _status(quote) == "PENDING_TRADE_REVIEW"


def test_wrong_role_endpoint_returns_403(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])
    # ВЭД cannot submit — the service refuses, the view maps it to 403.
    resp = _api(users["FOREIGN_TRADE_SPECIALIST"]).post(f"/api/v1/crm/quotes/{quote.id}/submit-for-review/")
    assert resp.status_code == 403
    assert _status(quote) == "DRAFT"


def test_my_approval_queue_endpoint(seller, deal):
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])
    QLS.submit_for_review(quote.id, users["SALES_MANAGER"])  # → PENDING_TRADE_REVIEW

    # ВЭД's queue contains the quote awaiting their confirmation.
    resp = _api(users["FOREIGN_TRADE_SPECIALIST"]).get("/api/v1/crm/quotes/my-approval-queue/")
    assert resp.status_code == 200
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id in ids

    # The director's queue does NOT (it is not at PENDING_APPROVAL yet).
    resp = _api(users["DIRECTOR"]).get("/api/v1/crm/quotes/my-approval-queue/")
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id not in ids


def test_send_to_client_allowed_for_sales_manager(seller, deal):
    """ADR-0002: the seller team sends its own internally-approved КП — not
    platform-admin-only. SALES_MANAGER on a READY_TO_SEND quote → 200 + SENT."""
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"], status_code="READY_TO_SEND")
    # Pre-set pdf_file so send_to_client skips WeasyPrint generation in the test.
    quote.pdf_file = "kp/already.pdf"
    quote.save(update_fields=["pdf_file"])

    resp = _api(users["SALES_MANAGER"]).post(f"/api/v1/crm/quotes/{quote.id}/send-to-client/")
    assert resp.status_code == 200, resp.data
    assert _status(quote) == "SENT"


def test_send_to_client_forbidden_for_non_sales_member(seller, deal):
    """A plain MEMBER (no SALES_MANAGER/OWNER role) cannot send → 403, КП unchanged."""
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"], status_code="READY_TO_SEND")
    resp = _api(users["MEMBER"]).post(f"/api/v1/crm/quotes/{quote.id}/send-to-client/")
    assert resp.status_code == 403
    assert _status(quote) == "READY_TO_SEND"


def test_send_to_client_rejects_unapproved_quote(seller, deal):
    """A DRAFT КП cannot be sent even by SALES_MANAGER — status guard → 400."""
    users = seller["users"]
    quote = _quote(deal, prepared_by=users["SALES_MANAGER"])  # DRAFT
    resp = _api(users["SALES_MANAGER"]).post(f"/api/v1/crm/quotes/{quote.id}/send-to-client/")
    assert resp.status_code == 400
    assert _status(quote) == "DRAFT"
