"""Service + endpoint tests for the КП visa chain (step-based) and the hand-off to the director in EDS (EDS-03).

Submit builds visa steps from the calculation task of the deal (EDS resolution assignees in zones goods/services
with an ERP user, not the author; wave 12 lead decision B1). Only the assigned assignee acts on their step — no
quote.review needed, and quote.review holders (the director) get no step. Same order = parallel. The last visa publishes
`quote.ready_for_approval` — the director approves in EDS, not as a step here. recall pulls the КП back while visas
are pending. DRAFT → PENDING_APPROVAL → (visas) → EDS → READY_TO_SEND.
"""

from decimal import Decimal

import pytest
from integration.tests import bus_support
from integration.tests.eds_support import assign_calc

from accounts.constants import Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus, StepTrigger
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


def _member(company, user, *, workspace_role=None, company_roles=()):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace_role) if workspace_role else None,
        company_roles=list(company_roles),
        is_primary=True,
        is_active=True,
        can_sell=False,  # explicit: permissions come from the roles, not the legacy flag
    )


@pytest.fixture
def seller(lookups):
    """Seller with a SALES_MANAGER (builds/submits), a HEAD (system role «Руководитель» — every permission, incl.
    quote.review — but no visa step: the director approves in EDS) and an ENGINEER without any role permission —
    the services assignee of the deal's resolution, who visas the КП."""
    from accounts.services.roles import ensure_default_company_roles

    company = Company.objects.create(name="Seller LLC", inn="7700000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    admin_role = ensure_default_company_roles(company)["HEAD"]
    sales_role = CompanyRole.objects.create(company=company, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])

    sales_user = _user("sales@seller.test")
    _member(company, sales_user, workspace_role="SALES_MANAGER", company_roles=[sales_role])
    head_user = _user("head@seller.test")
    _member(company, head_user, workspace_role="MEMBER", company_roles=[admin_role])
    engineer = _user("engineer@seller.test")
    _member(company, engineer, workspace_role="MEMBER")
    return {"company": company, "sales": sales_user, "head": head_user, "admin_role": admin_role, "engineer": engineer}


@pytest.fixture
def client_co(lookups):
    company = Company.objects.create(name="Client LLC", inn="6600000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


@pytest.fixture
def deal(seller, client_co):
    deal = Deal.objects.create(
        title="Chain Deal", company=client_co, manager=seller["sales"], stage=DealStage.objects.get(code="DRAFT")
    )
    assign_calc(deal, (seller["engineer"], 12, "services"))  # резолюция EDS: инженер — исполнитель услуг
    return deal


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


def _ready_events():
    return bus_support.published("quote.ready_for_approval")


def test_submit_builds_visa_steps_without_a_director_step(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    _, err = QLS.submit_for_review(quote.id, seller["sales"])
    assert err is None and _status(quote) == "PENDING_APPROVAL"
    steps = list(quote.approval_steps.all())
    assert [s.participation for s in steps] == [StepParticipation.APPROVER]
    assert steps[0].approver.user_id == seller["engineer"].id and steps[0].status == StepStatus.PENDING
    assert steps[0].trigger_reason == StepTrigger.CALC_VISA
    assert _ready_events() == [], "КП уходит директору после виз"


def test_last_visa_sends_the_quote_to_the_director_in_eds(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    _, err = act_on_step(step.id, seller["engineer"], "APPROVE")
    assert err is None and _status(quote) == "PENDING_APPROVAL"
    step.refresh_from_db()
    assert step.status == StepStatus.APPROVED and step.acted_by_id == seller["engineer"].id
    assert len(_ready_events()) == 1


def test_reject_returns_to_draft(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    _, err = act_on_step(step.id, seller["engineer"], "REJECT", comment="дорого")
    assert err is None and _status(quote) == "DRAFT"
    step.refresh_from_db()
    assert step.status == StepStatus.REJECTED and step.comment == "дорого"
    assert _ready_events() == []


def test_recall_returns_to_draft(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    _, err = recall_quote(quote.id, seller["sales"])
    assert err is None and _status(quote) == "DRAFT"
    assert quote.approval_steps.filter(status=StepStatus.RECALLED).exists()


def test_non_permitted_cannot_act(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    # Only the assigned assignee visas: neither the sales manager nor the director (quote.review holder) can.
    for other in (seller["sales"], seller["head"]):
        _, err = act_on_step(step.id, other, "APPROVE")
        assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "PENDING_APPROVAL"


def test_director_gets_no_visa_step_in_erp(seller, deal):
    """The director holds quote.review (role «Руководитель») but approves only in EDS — no ERP visa step."""
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    assert not quote.approval_steps.filter(approver__user=seller["head"]).exists()


def test_quote_without_calc_task_has_no_visas_and_goes_to_eds(seller, client_co):
    bare = Deal.objects.create(title="No task", company=client_co, stage=DealStage.objects.get(code="DRAFT"))
    quote = _quote(bare, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    assert not quote.approval_steps.exists() and _status(quote) == "PENDING_APPROVAL"
    (event,) = _ready_events()
    assert event["data"]["payload"]["required_zones"] == [] and event["data"]["payload"]["visas"] == []


def test_every_assignee_visas_before_the_director(seller, deal):
    """Two assignees (goods, services) give two parallel visa steps; the КП goes to EDS after both visas."""
    supply = _user("supply@seller.test")
    _member(seller["company"], supply, workspace_role="MEMBER")
    assign_calc(deal, (supply, 11, "goods"), (seller["engineer"], 12, "services"))

    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    supply_step = quote.approval_steps.get(approver__user=supply)
    engineer_step = quote.approval_steps.get(approver__user=seller["engineer"])
    assert supply_step.order == engineer_step.order == 1  # parallel

    assert act_on_step(supply_step.id, supply, "APPROVE")[1] is None
    assert _ready_events() == []
    assert act_on_step(engineer_step.id, seller["engineer"], "APPROVE")[1] is None
    assert _status(quote) == "PENDING_APPROVAL"
    (event,) = _ready_events()
    visas = {(v["zone"], v["by"]["crm_user_id"]) for v in event["data"]["payload"]["visas"]}
    assert visas == {("goods", 11), ("services", 12)} and event["data"]["payload"]["required_zones"] == [
        "goods",
        "services",
    ]


def test_recall_after_hand_over_to_the_director_is_refused(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    act_on_step(step.id, seller["engineer"], "APPROVE")
    _, err = recall_quote(quote.id, seller["sales"])
    assert err == "QUOTE_AWAITING_DIRECTOR" and _status(quote) == "PENDING_APPROVAL"
    resp = _api(seller["sales"]).post(f"/api/v1/crm/quotes/{quote.id}/recall/")
    assert resp.status_code == 409 and resp.data["detail"] == "QUOTE_AWAITING_DIRECTOR"


def test_submit_gate_requires_quote_build_permission(seller, deal):
    """ADR-0005 Phase E U3 Step 2: the submit gate is now the quote.build CompanyRole permission,
    not the SALES_MANAGER WorkspaceRole. A member whose roles omit quote.build is denied."""
    quote = _quote(deal, prepared_by=seller["sales"])
    noperm_role = CompanyRole.objects.create(company=seller["company"], name="Без прав", permissions=[])
    noperm_user = _user("noperm@seller.test")
    _member(seller["company"], noperm_user, workspace_role="MEMBER", company_roles=[noperm_role])
    _, err = QLS.submit_for_review(quote.id, noperm_user)
    assert err == "ROLE_NOT_PERMITTED" and _status(quote) == "DRAFT"


def test_submit_allowed_for_head_role(seller, deal):
    """«Руководитель» holds every back-office permission incl. quote.build, so under the permission
    model they may submit — a deliberate widening vs the old SALES_MANAGER-only gate."""
    quote = _quote(deal, prepared_by=seller["sales"])
    _, err = QLS.submit_for_review(quote.id, seller["head"])  # head = MEMBER workspace + HEAD role
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


def test_event_log_step_approved_and_sent_to_director(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    act_on_step(step.id, seller["engineer"], "APPROVE")

    approved = _last_event(quote, "quote.approval_step_approved")
    assert approved is not None
    assert approved.action == "Шаг согласования пройден"  # human-readable RU, not a raw key
    assert "participation" in approved.event_params

    handed = _last_event(quote, "quote.sent_to_director")
    assert handed is not None
    assert handed.action == "КП передано директору на одобрение"
    quote.refresh_from_db()
    assert handed.event_params == {"number": quote.number, "revision": 1}


def test_event_log_step_rejected(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    act_on_step(step.id, seller["engineer"], "REJECT", comment="дорого")

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
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    resp = _api(seller["engineer"]).post(
        f"/api/v1/crm/quotes/{quote.id}/approval-act/", {"step_id": step.id, "decision": "APPROVE"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert _status(quote) == "PENDING_APPROVAL" and len(_ready_events()) == 1


def test_recall_endpoint(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    resp = _api(seller["sales"]).post(f"/api/v1/crm/quotes/{quote.id}/recall/")
    assert resp.status_code == 200, resp.data
    assert _status(quote) == "DRAFT"


def test_my_approval_queue_endpoint(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    # The assignee's queue contains the quote awaiting their visa.
    resp = _api(seller["engineer"]).get("/api/v1/crm/quotes/my-approval-queue/")
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id in ids
    # Neither the sales manager nor the director (quote.review, not assigned) sees it in the visa queue.
    for other in (seller["sales"], seller["head"]):
        resp = _api(other).get("/api/v1/crm/quotes/my-approval-queue/")
        ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
        assert quote.id not in ids
