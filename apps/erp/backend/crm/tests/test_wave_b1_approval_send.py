"""Wave B1 — remove send-path friction (spec-kp-station-target-2026-07-21).

Three deliverables, benchmark = Salesforce CPQ Advanced Approvals:

  1. Auto-approve a solo/self chain: when the ONLY approver of every step is the submitter
     themselves, submit auto-advances straight to READY_TO_SEND (zero ceremony), with an
     audited «согласовано автоматически» event. A genuine cross-person chain (a different head,
     a below-floor escalation to someone else) is UNTOUCHED and routes exactly as today.
  2. Approval-preview read endpoint (Salesforce Approval Preview): who WOULD approve if
     submitted now — read-only, builds/persists nothing.
  3. valid_until default (Odoo Default Validity): on send, a still-empty valid_until is filled
     from the company's default_offer_validity_days; left None when unconfigured.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from accounts.constants import Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanySettings, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus, StepTrigger
from crm.services.approvals import preview_approval_chain
from crm.services.quotes import QuoteLifecycleService as QLS
from master_data.models import Country

pytestmark = pytest.mark.django_db

QUOTE_STATUSES = ["DRAFT", "PENDING_APPROVAL", "READY_TO_SEND", "SENT", "APPROVED", "REJECTED"]
DEAL_STAGES = ["DRAFT", "RFQ_OPEN", "SOURCING", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED"]
WORKSPACE_ROLES = ["OWNER", "SALES_MANAGER", "MEMBER"]


@pytest.fixture
def lookups(db):
    for code in QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in WORKSPACE_ROLES:
        WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in DEAL_STAGES:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(company, user, *, workspace_role="MEMBER", company_role=None):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace_role) if workspace_role else None,
        company_role=company_role,
        is_primary=True,
        is_active=True,
        can_sell=False,  # permissions come from company_role, not the legacy flag
    )


def _seller_company(name, inn):
    company = Company.objects.create(
        name=name,
        inn=inn,
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return company


@pytest.fixture
def solo(lookups):
    """A one-person seller: the sole member holds the is_system admin role (every permission,
    incl. quote.build + quote.approve_final) — so they are both submitter AND the only approver."""
    company = _seller_company("Solo LLC", "7700000010")
    admin_role = CompanyRole.objects.create(company=company, name="Администратор компании", is_system=True)
    owner = _user("owner@solo.test")
    _member(company, owner, workspace_role="OWNER", company_role=admin_role)
    return {"company": company, "owner": owner}


@pytest.fixture
def two_person(lookups):
    """A two-person seller: SALES (quote.build only, submits) + HEAD (is_system, approves).
    The head is a DIFFERENT user than the submitter → a genuine cross-person chain."""
    company = _seller_company("Duo LLC", "7700000011")
    admin_role = CompanyRole.objects.create(company=company, name="Администратор компании", is_system=True)
    sales_role = CompanyRole.objects.create(company=company, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])
    sales = _user("sales@duo.test")
    _member(company, sales, workspace_role="SALES_MANAGER", company_role=sales_role)
    head = _user("head@duo.test")
    _member(company, head, workspace_role="MEMBER", company_role=admin_role)
    return {"company": company, "sales": sales, "head": head}


def _client_co(lookups):
    company = Company.objects.create(name="Buyer LLC", inn="6600000010")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


def _deal(company, manager, stage="DRAFT", client=None):
    return Deal.objects.create(
        title="B1 Deal", company=company, manager=manager, client=client, stage=DealStage.objects.get(code=stage)
    )


def _quote(deal, prepared_by, seller_company, *, status="DRAFT"):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code=status),
        prepared_by=prepared_by,
        seller_company=seller_company,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


def _status(quote):
    quote.refresh_from_db()
    return quote.status.code


def _clean_econ(below_floor=False):
    return {
        "fx_missing": False,
        "below_cost": False,
        "below_floor": below_floor,
        "gross_margin_percent": Decimal("20.00"),
    }


# ─── Deliverable 1: auto-approve solo, real chain still routes ────────────────


def test_solo_chain_auto_approves_to_ready_to_send(solo):
    """The only approver is the submitter → submit auto-passes the chain straight to
    READY_TO_SEND, with an audited «согласовано автоматически» event and the head step APPROVED."""
    client_co = _client_co(None)
    deal = _deal(client_co, solo["owner"])
    quote = _quote(deal, solo["owner"], solo["company"])

    q, err = QLS.submit_for_review(quote.id, solo["owner"])
    assert err is None
    assert _status(quote) == "READY_TO_SEND"

    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    assert head_step.status == StepStatus.APPROVED
    assert head_step.acted_by_id == solo["owner"].id

    auto_evt = ActivityLog.objects.filter(
        entity_type="quote", entity_id=quote.id, event_code="quote.approval_auto"
    ).first()
    assert auto_evt is not None
    assert auto_evt.action == "Согласовано автоматически"


def test_real_chain_with_different_head_still_routes(two_person):
    """Two-person company, head ≠ submitter → NOT auto-approved: stays PENDING_APPROVAL, head
    step still PENDING (routes exactly as today)."""
    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    quote = _quote(deal, two_person["sales"], two_person["company"])

    q, err = QLS.submit_for_review(quote.id, two_person["sales"])
    assert err is None
    assert _status(quote) == "PENDING_APPROVAL"

    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    assert head_step.status == StepStatus.PENDING
    assert head_step.approver.user_id == two_person["head"].id
    # No auto-approve event was written.
    assert not ActivityLog.objects.filter(
        entity_type="quote", entity_id=quote.id, event_code="quote.approval_auto"
    ).exists()


def test_below_floor_with_different_head_still_escalates(two_person):
    """A below-floor КП whose head is a DIFFERENT person must STILL escalate — auto-approve
    must never weaken a genuine cross-person chain (control preserved, only ritual removed)."""
    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    quote = _quote(deal, two_person["sales"], two_person["company"])

    with mock.patch(
        "crm.services.quotes.lifecycle.compute_quote_economics", return_value=_clean_econ(below_floor=True)
    ):
        q, err = QLS.submit_for_review(quote.id, two_person["sales"])
    assert err is None
    assert _status(quote) == "PENDING_APPROVAL"

    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    assert head_step.status == StepStatus.PENDING
    assert head_step.trigger_reason == StepTrigger.BELOW_FLOOR_ESCALATION
    assert head_step.approver.user_id == two_person["head"].id


# ─── Deliverable 2: approval-preview (read-only, no side effects) ─────────────


def test_preview_solo_would_auto_approve_no_side_effects(solo):
    client_co = _client_co(None)
    deal = _deal(client_co, solo["owner"])
    quote = _quote(deal, solo["owner"], solo["company"])

    data, err = preview_approval_chain(quote.id, solo["owner"])
    assert err is None
    assert data["would_auto_approve"] is True
    assert data["below_floor"] is False
    assert len(data["steps"]) == 1
    head = data["steps"][0]
    assert head["participation"] == StepParticipation.HEAD
    assert head["is_submitter"] is True and head["is_assigned"] is True
    assert head["user_id"] == solo["owner"].id
    # READ-ONLY: no steps were persisted and the КП is untouched (still DRAFT).
    assert quote.approval_steps.count() == 0
    assert _status(quote) == "DRAFT"


def test_preview_two_person_would_route(two_person):
    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    quote = _quote(deal, two_person["sales"], two_person["company"])

    data, err = preview_approval_chain(quote.id, two_person["sales"])
    assert err is None
    assert data["would_auto_approve"] is False
    head = next(step for step in data["steps"] if step["participation"] == StepParticipation.HEAD)
    assert head["is_submitter"] is False
    assert head["user_id"] == two_person["head"].id
    assert quote.approval_steps.count() == 0


def test_preview_endpoint_returns_shape(two_person):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    quote = _quote(deal, two_person["sales"], two_person["company"])

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(two_person['sales']).access_token}")
    resp = api.get(f"/api/v1/crm/quotes/{quote.id}/approval-preview/")
    assert resp.status_code == 200, resp.data
    assert set(resp.data.keys()) == {"would_auto_approve", "below_floor", "steps"}
    assert quote.approval_steps.count() == 0


# ─── Deliverable 3: valid_until default on send ──────────────────────────────


def _sendable_quote(default_validity_days):
    """A READY_TO_SEND КП owned by a seller, with a registered-client recipient
    and a deal already in CALCULATING (so send can advance it to QUOTE_SENT)."""
    company = _seller_company("Ready Seller LLC", "7700000012")
    if default_validity_days is not None:
        CompanySettings.objects.create(company=company, default_offer_validity_days=default_validity_days)
    else:
        CompanySettings.objects.create(company=company)
    seller_user = _user("seller@ready.test")
    admin_role = CompanyRole.objects.create(company=company, name="Администратор компании", is_system=True)
    _member(company, seller_user, workspace_role="OWNER", company_role=admin_role)

    buyer_user = _user("buyer@ready.test")
    client_co = _client_co(None)
    deal = _deal(client_co, seller_user, stage="CALCULATING", client=buyer_user)
    quote = _quote(deal, seller_user, company, status="READY_TO_SEND")
    return seller_user, quote


def test_valid_until_populated_on_send_when_configured(lookups):
    seller_user, quote = _sendable_quote(default_validity_days=14)
    assert quote.valid_until is None
    with mock.patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=_clean_econ()):
        QLS.send_to_client(quote.id, seller_user)
    quote.refresh_from_db()
    assert quote.valid_until == timezone.localdate() + timedelta(days=14)


def test_valid_until_left_none_when_company_unconfigured(lookups):
    seller_user, quote = _sendable_quote(default_validity_days=None)
    with mock.patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=_clean_econ()):
        QLS.send_to_client(quote.id, seller_user)
    quote.refresh_from_db()
    assert quote.valid_until is None


# ─── Send must drop a stale pre-send PDF cache ───────────────────────────────


def test_send_invalidates_cached_draft_pdf(lookups):
    """Prod incident 2026-07-26: «Предпросмотр PDF» seconds before send caches a DRAFT render
    («ЧЕРНОВИК» stamp, placeholder number) — and send_quote_email only renders when pdf_file
    is EMPTY, so the client received the stale draft. Send re-mints the document identity
    (№, frozen prices) → it must blank pdf_file so the email/public link re-render fresh."""
    from django.core.files.base import ContentFile

    seller_user, quote = _sendable_quote(default_validity_days=None)
    # Simulate the pre-send preview: a cached DRAFT render sits on the quote.
    quote.pdf_file.save("draft-preview.pdf", ContentFile(b"%PDF-1.7 stale draft"), save=True)
    assert quote.pdf_file

    with mock.patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=_clean_econ()):
        QLS.send_to_client(quote.id, seller_user)

    quote.refresh_from_db()
    assert not quote.pdf_file, "send_to_client must drop the stale pre-send PDF cache"
    assert quote.frozen_at is not None
    assert quote.number  # the minted citable № the fresh render will print
