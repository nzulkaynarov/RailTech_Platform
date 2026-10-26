"""FIX-55 / D-02, D-11: автор КП не согласует своё КП; суперпользователь за другого — «от имени».

D-02: автор КП попадал в проверяющие своего же КП и мог закрыть шаг APPROVER. Теперь (волна 12, Б1) визы — исполнители
задания расчёта; автор-исполнитель исключён из шагов (в цепочке и в превью) и визирует свою зону самой отправкой, а
действие автора на шаге APPROVER отклоняется `SELF_APPROVAL_NOT_ALLOWED`. Визировать некому, кроме автора, — КП сразу уходит директору в EDS (EDS-03,
автосогласования больше нет). D-11: суперпользователь закрывает шаг за другого — разрешено, но журнал помечает «от имени».
"""

# flake8: noqa: F811  (фикстуры импортируются из соседних тестов и подставляются аргументами)

import pytest
from integration.tests import bus_support
from integration.tests.eds_support import assign_calc

from accounts.constants import Permission
from accounts.models import CompanyRole
from crm.models import ActivityLog
from crm.models.approvals import QuoteApprovalStep, StepParticipation, StepStatus, StepTrigger
from crm.services.approvals import act_on_step, preview_approval_chain
from crm.services.quotes import QuoteLifecycleService as QLS
from crm.tests.test_quote_approval_chain import (  # noqa: F401
    _member,
    _quote,
    _status,
    _user,
    client_co,
    deal,
    lookups,
    seller,
)

pytestmark = pytest.mark.django_db


def _author_supply(seller):
    """Автор КП — снабженец, исполнитель зоны goods резолюции (quote.build, без quote.review)."""
    role = CompanyRole.objects.create(
        company=seller["company"], name="Снабжение", permissions=[Permission.QUOTE_BUILD.value]
    )
    author = _user("supply-author@seller.test")
    _member(seller["company"], author, workspace_role="MEMBER", company_roles=[role])
    return author


def test_author_is_not_a_visa_step_of_own_quote(seller, deal):
    author = _author_supply(seller)
    assign_calc(deal, (author, 11, "goods"), (seller["engineer"], 12, "services"))
    quote = _quote(deal, prepared_by=author)

    _, err = QLS.submit_for_review(quote.id, author)

    assert err is None
    steps = quote.approval_steps.filter(participation=StepParticipation.APPROVER)
    assert [step.approver.user_id for step in steps] == [seller["engineer"].id]


def test_preview_excludes_author_from_visas(seller, deal):
    author = _author_supply(seller)
    assign_calc(deal, (author, 11, "goods"), (seller["engineer"], 12, "services"))
    quote = _quote(deal, prepared_by=author)

    preview, err = preview_approval_chain(quote.id, author)

    assert err is None
    assert [s["user_id"] for s in preview["steps"] if s["trigger"] == StepTrigger.CALC_VISA] == [seller["engineer"].id]


def test_author_cannot_act_on_approver_step(seller, deal):
    """Шаг APPROVER на имя автора (старая цепочка / назначение изменили позже) автор закрыть не может."""
    author = _author_supply(seller)
    quote = _quote(deal, prepared_by=author)
    QLS.submit_for_review(quote.id, author)
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    author_member = author.memberships.get(company=seller["company"])
    QuoteApprovalStep.objects.filter(pk=step.pk).update(approver=author_member)

    _, err = act_on_step(step.id, author, "APPROVE")

    assert err == "SELF_APPROVAL_NOT_ALLOWED"
    step.refresh_from_db()
    assert step.status == StepStatus.PENDING and _status(quote) == "PENDING_APPROVAL"


def test_author_cannot_approve_via_endpoint(seller, deal):
    from crm.tests.test_quote_approval_chain import _api

    author = _author_supply(seller)
    quote = _quote(deal, prepared_by=author)
    QLS.submit_for_review(quote.id, author)
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    QuoteApprovalStep.objects.filter(pk=step.pk).update(approver=author.memberships.get(company=seller["company"]))

    response = _api(author).post(
        f"/api/v1/crm/quotes/{quote.id}/approval-act/", {"step_id": step.id, "decision": "APPROVE"}, format="json"
    )

    assert response.status_code == 403, response.content
    assert response.json()["detail"] == "SELF_APPROVAL_NOT_ALLOWED"


def test_author_alone_goes_straight_to_the_director_in_eds(seller, deal):
    """Исполнитель резолюции — только сам автор: шагов нет, его зона завизирована отправкой, КП сразу у директора."""
    author = _author_supply(seller)
    assign_calc(deal, (author, 11, "goods"))
    quote = _quote(deal, prepared_by=author)

    _, err = QLS.submit_for_review(quote.id, author)

    assert err is None
    assert _status(quote) == "PENDING_APPROVAL" and not quote.approval_steps.exists()
    (event,) = bus_support.published("quote.ready_for_approval")
    assert [(v["zone"], v["by"]["crm_user_id"]) for v in event["data"]["payload"]["visas"]] == [("goods", 11)]


def test_superuser_acting_for_the_approver_is_marked_on_behalf(seller, deal):
    admin = _user("root@seller.test")
    admin.is_superuser = True
    admin.save(update_fields=["is_superuser"])
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)

    _, err = act_on_step(step.id, admin, "APPROVE")

    assert err is None and _status(quote) == "PENDING_APPROVAL"
    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_approved").latest("id")
    assert event.user_id == admin.id
    assert event.event_params["on_behalf_of_user_id"] == seller["engineer"].id
    assert "engineer@seller.test" in event.event_params["on_behalf_of"]
    assert "от имени" in event.detail


def test_superuser_rejecting_for_the_approver_is_marked_on_behalf(seller, deal):
    admin = _user("root2@seller.test")
    admin.is_superuser = True
    admin.save(update_fields=["is_superuser"])
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)

    act_on_step(step.id, admin, "REJECT", comment="нет")

    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_rejected").latest("id")
    assert event.event_params["on_behalf_of_user_id"] == seller["engineer"].id
    assert event.event_params["comment"] == "нет"


def test_regular_approver_is_not_marked_on_behalf(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)

    act_on_step(step.id, seller["engineer"], "APPROVE")

    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_approved").latest("id")
    assert "on_behalf_of" not in event.event_params
