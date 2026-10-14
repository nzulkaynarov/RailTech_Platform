"""Service + endpoint tests for the UNIFIED КП approval chain (step-based).

Submit builds a permission-driven step list: an optional intermediate reviewer
(quote.review) + a mandatory final approver / руководитель (quote.approve_final).
Same order = parallel; the head is always last. act_on_step advances the chain;
recall pulls it back. DRAFT → PENDING_APPROVAL → (steps approved) → READY_TO_SEND.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.constants import Permission
from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    WorkspaceRole,
)
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus
from crm.services.approvals import act_on_step, recall_quote
from crm.services.quotes import QuoteLifecycleService as QLS
from master_data.models import Country

pytestmark = pytest.mark.django_db

QUOTE_STATUSES = ["DRAFT", "PENDING_TRADE_REVIEW", "PENDING_APPROVAL", "READY_TO_SEND", "SENT", "APPROVED", "REJECTED"]
WORKSPACE_ROLES = ["OWNER", "SALES_MANAGER", "MEMBER"]


@pytest.fixture
def lookups(db):
    for code in QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in WORKSPACE_ROLES:
        WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(company, user, *, workspace_role=None, company_role=None):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace_role) if workspace_role else None,
        company_role=company_role,
        is_primary=True,
        is_active=True,
        can_sell=False,  # explicit: permissions come from company_role, not the legacy flag
    )


@pytest.fixture
def seller(lookups):
    """Seller with a SALES_MANAGER (builds/submits, no approval rights) and a HEAD
    (company-admin role → quote.approve_final). Operational subscription so send is allowed."""
    company = Company.objects.create(name="Seller LLC", inn="7700000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    SupplierSubscription.objects.create(
        company=company, plan="PREMIUM", status="ACTIVE", valid_until=timezone.localdate() + timedelta(days=365)
    )
    admin_role = CompanyRole.objects.create(company=company, name="Администратор компании", is_system=True)
    sales_role = CompanyRole.objects.create(company=company, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])

    sales_user = _user("sales@seller.test")
    _member(company, sales_user, workspace_role="SALES_MANAGER", company_role=sales_role)
    head_user = _user("head@seller.test")
    # Neutral workspace role (not OWNER/SALES_MANAGER) → cannot submit; approval rights come
    # purely from the is-system company role (quote.approve_final).
    _member(company, head_user, workspace_role="MEMBER", company_role=admin_role)
    return {"company": company, "sales": sales_user, "head": head_user, "admin_role": admin_role}


@pytest.fixture
def client_co(lookups):
    company = Company.objects.create(name="Client LLC", inn="6600000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


@pytest.fixture
def deal(seller, client_co):
    return Deal.objects.create(
        title="Chain Deal", company=client_co, manager=seller["sales"], stage=DealStage.objects.get(code="DRAFT")
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


def test_submit_builds_chain_with_mandatory_head(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    _, err = QLS.submit_for_review(quote.id, seller["sales"])
    assert err is None and _status(quote) == "PENDING_APPROVAL"
    steps = list(quote.approval_steps.all())
    head = [s for s in steps if s.participation == StepParticipation.HEAD]
    assert len(head) == 1 and head[0].is_mandatory and head[0].status == StepStatus.PENDING


def test_head_approval_makes_ready(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    _, err = act_on_step(head_step.id, seller["head"], "APPROVE")
    assert err is None and _status(quote) == "READY_TO_SEND"
    head_step.refresh_from_db()
    assert head_step.status == StepStatus.APPROVED and head_step.acted_by_id == seller["head"].id


def test_reject_returns_to_draft(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    _, err = act_on_step(head_step.id, seller["head"], "REJECT", comment="дорого")
    assert err is None and _status(quote) == "DRAFT"
    head_step.refresh_from_db()
    assert head_step.status == StepStatus.REJECTED and head_step.comment == "дорого"


def test_recall_returns_to_draft(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    _, err = recall_quote(quote.id, seller["sales"])
    assert err is None and _status(quote) == "DRAFT"
    assert quote.approval_steps.filter(status=StepStatus.RECALLED).exists()


def test_non_permitted_cannot_act(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    # The sales manager has no quote.approve_final → cannot act on the head step.
    _, err = act_on_step(head_step.id, seller["sales"], "APPROVE")
    assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "PENDING_APPROVAL"


def test_reviewer_then_head(seller, deal):
    """A dedicated reviewer (quote.review, not head) adds an intermediate step acted first."""
    reviewer_role = CompanyRole.objects.create(
        company=seller["company"], name="ВЭД", permissions=[Permission.QUOTE_REVIEW.value]
    )
    reviewer = _user("ved@seller.test")
    _member(seller["company"], reviewer, workspace_role="MEMBER", company_role=reviewer_role)

    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    review_step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    assert review_step.order < head_step.order

    # Head can't jump the queue before the reviewer acts.
    _, err = act_on_step(head_step.id, seller["head"], "APPROVE")
    assert err == "STEP_NOT_ACTIVE" and _status(quote) == "PENDING_APPROVAL"

    assert act_on_step(review_step.id, reviewer, "APPROVE")[1] is None
    assert act_on_step(head_step.id, seller["head"], "APPROVE")[1] is None
    assert _status(quote) == "READY_TO_SEND"


def test_submit_gate_requires_quote_build_permission(seller, deal):
    """ADR-0005 Phase E U3 Step 2: the submit gate is now the quote.build CompanyRole permission,
    not the SALES_MANAGER WorkspaceRole. A member whose CompanyRole omits quote.build (and no
    can_sell fallback) is denied."""
    quote = _quote(deal, prepared_by=seller["sales"])
    noperm_role = CompanyRole.objects.create(company=seller["company"], name="Наблюдатель", permissions=[])
    noperm_user = _user("noperm@seller.test")
    _member(seller["company"], noperm_user, workspace_role="MEMBER", company_role=noperm_role)
    _, err = QLS.submit_for_review(quote.id, noperm_user)
    assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "DRAFT"


def test_submit_allowed_for_is_system_admin(seller, deal):
    """The company admin (is_system CompanyRole) holds every permission incl. quote.build, so under
    the permission model they may submit — a deliberate widening vs the old SALES_MANAGER-only gate."""
    quote = _quote(deal, prepared_by=seller["sales"])
    _, err = QLS.submit_for_review(quote.id, seller["head"])  # head = MEMBER workspace + is_system role
    assert err is None


def test_send_to_client_blocked_until_ready(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    with pytest.raises(ValueError):
        QLS.send_to_client(quote.id, seller["sales"])


# ─── structured event logging (E1 i18n timeline) ────────────────────────────
def _last_event(quote, event_code):
    return (
        ActivityLog.objects.filter(entity_type="quote", entity_id=quote.id, event_code=event_code)
        .order_by("-id")
        .first()
    )


def test_event_log_step_approved_and_complete(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    act_on_step(head_step.id, seller["head"], "APPROVE")

    approved = _last_event(quote, "quote.approval_step_approved")
    assert approved is not None
    assert approved.action == "Шаг согласования пройден"  # human-readable RU, not a raw key
    assert "participation" in approved.event_params

    complete = _last_event(quote, "quote.approval_complete")
    assert complete is not None
    assert complete.action == "Согласование КП завершено"
    assert complete.event_params == {}


def test_event_log_step_rejected(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    act_on_step(head_step.id, seller["head"], "REJECT", comment="дорого")

    rejected = _last_event(quote, "quote.approval_step_rejected")
    assert rejected is not None
    assert rejected.action == "Согласование отклонено"
    assert rejected.event_params == {"comment": "дорого"}


def test_event_log_recalled(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    recall_quote(quote.id, seller["sales"])

    recalled = _last_event(quote, "quote.approval_recalled")
    assert recalled is not None
    assert recalled.action == "КП отозван из согласования"
    assert recalled.event_params == {}


# ─── DRF endpoint tests ─────────────────────────────────────────────────────
def _api(user):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def test_approval_act_endpoint(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    resp = _api(seller["head"]).post(
        f"/api/v1/crm/quotes/{quote.id}/approval-act/", {"step_id": head_step.id, "decision": "APPROVE"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert _status(quote) == "READY_TO_SEND"


def test_recall_endpoint(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    resp = _api(seller["sales"]).post(f"/api/v1/crm/quotes/{quote.id}/recall/")
    assert resp.status_code == 200, resp.data
    assert _status(quote) == "DRAFT"


def test_my_approval_queue_endpoint(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    # The head's queue contains the quote awaiting their approval.
    resp = _api(seller["head"]).get("/api/v1/crm/quotes/my-approval-queue/")
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id in ids
    # The sales manager (no approval right) does not see it in the approval queue.
    resp = _api(seller["sales"]).get("/api/v1/crm/quotes/my-approval-queue/")
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id not in ids
