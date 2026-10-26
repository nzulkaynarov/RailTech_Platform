"""Wave B1 — remove send-path friction (spec-kp-station-target-2026-07-21), adapted to EDS-03 (wave 12).

Deliverables, benchmark = Salesforce CPQ Advanced Approvals:

  1. Visa chain routing: the calculation-task assignees (EDS resolution) other than the submitter visa the КП; with no
     one else to visa it goes straight to the director's approval route in EDS (`quote.ready_for_approval`). The former auto-approve of a
     solo chain is gone together with the ERP director step — approval is the director's decision in EDS.
  2. Approval-preview read endpoint (Salesforce Approval Preview): who WOULD visa if submitted now — read-only,
     builds/persists nothing.
  3. valid_until default (Odoo Default Validity): on send, a still-empty valid_until is filled
     from the company's default_offer_validity_days; left None when unconfigured.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone
from integration.tests import bus_support
from integration.tests.eds_support import assign_calc

from accounts.constants import Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanySettings, CompanyType, CustomUser, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus
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


def _member(company, user, *, workspace_role="MEMBER", company_roles=None):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace_role) if workspace_role else None,
        company_roles=company_roles or [],
        is_primary=True,
        is_active=True,
        can_sell=False,  # permissions come from the roles, not the legacy flag
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
    """A one-person seller: the sole member holds the «Руководитель» role (every permission) and there is no
    calculation task — so there is no one to visa their КП."""
    company = _seller_company("Solo LLC", "7700000010")
    admin_role = ensure_default_company_roles(company)["HEAD"]
    owner = _user("owner@solo.test")
    _member(company, owner, workspace_role="OWNER", company_roles=[admin_role])
    return {"company": company, "owner": owner}


@pytest.fixture
def two_person(lookups):
    """A two-person seller: SALES (quote.build only, submits) + HEAD («Руководитель»). Tests assign the head as the
    services assignee of the deal's resolution → a genuine cross-person visa chain."""
    company = _seller_company("Duo LLC", "7700000011")
    admin_role = ensure_default_company_roles(company)["HEAD"]
    sales_role = CompanyRole.objects.create(company=company, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])
    sales = _user("sales@duo.test")
    _member(company, sales, workspace_role="SALES_MANAGER", company_roles=[sales_role])
    head = _user("head@duo.test")
    _member(company, head, workspace_role="MEMBER", company_roles=[admin_role])
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


# ─── Deliverable 1: visa chain routing; no one else to visa → straight to the director in EDS ──────


def test_solo_seller_goes_straight_to_the_director_in_eds(solo):
    """The submitter is the only quote.review holder → no visa steps; the КП goes to the director's approval
    route in EDS at once (PENDING_APPROVAL + quote.ready_for_approval), never self-approved to READY_TO_SEND."""
    client_co = _client_co(None)
    deal = _deal(client_co, solo["owner"])
    quote = _quote(deal, solo["owner"], solo["company"])

    q, err = QLS.submit_for_review(quote.id, solo["owner"])
    assert err is None
    assert _status(quote) == "PENDING_APPROVAL"
    assert not quote.approval_steps.exists()
    assert len(bus_support.published("quote.ready_for_approval")) == 1


def test_real_chain_with_a_different_reviewer_still_routes(two_person):
    """Two-person company, assignee ≠ submitter → the assignee visas first; nothing goes to EDS yet."""
    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    assign_calc(deal, (two_person["head"], 12, "services"))
    quote = _quote(deal, two_person["sales"], two_person["company"])

    q, err = QLS.submit_for_review(quote.id, two_person["sales"])
    assert err is None
    assert _status(quote) == "PENDING_APPROVAL"

    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    assert step.status == StepStatus.PENDING
    assert step.approver.user_id == two_person["head"].id
    assert bus_support.published("quote.ready_for_approval") == []


# ─── Deliverable 2: approval-preview (read-only, no side effects) ─────────────


def test_preview_solo_has_no_visa_steps_and_no_side_effects(solo):
    client_co = _client_co(None)
    deal = _deal(client_co, solo["owner"])
    quote = _quote(deal, solo["owner"], solo["company"])

    data, err = preview_approval_chain(quote.id, solo["owner"])
    assert err is None
    assert data == {"below_floor": False, "steps": []}
    # READ-ONLY: no steps were persisted and the КП is untouched (still DRAFT).
    assert quote.approval_steps.count() == 0
    assert _status(quote) == "DRAFT"


def test_preview_two_person_would_route(two_person):
    client_co = _client_co(None)
    deal = _deal(client_co, two_person["sales"])
    assign_calc(deal, (two_person["head"], 12, "services"))
    quote = _quote(deal, two_person["sales"], two_person["company"])

    data, err = preview_approval_chain(quote.id, two_person["sales"])
    assert err is None
    (step,) = data["steps"]
    assert step["participation"] == StepParticipation.APPROVER
    assert step["is_submitter"] is False
    assert step["user_id"] == two_person["head"].id
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
    assert set(resp.data.keys()) == {"below_floor", "steps"}
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
    admin_role = ensure_default_company_roles(company)["HEAD"]
    _member(company, seller_user, workspace_role="OWNER", company_roles=[admin_role])

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
