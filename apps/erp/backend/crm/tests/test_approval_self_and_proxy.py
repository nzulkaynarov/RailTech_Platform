"""FIX-55 / D-02, D-11: автор КП не согласует своё КП; суперпользователь за другого — «от имени».

D-02: автор КП, держащий `quote.review`, попадал в проверяющие своего же КП и мог закрыть шаг APPROVER.
Теперь автор исключён из проверяющих (в цепочке и в превью), а действие автора на шаге APPROVER
отклоняется `SELF_APPROVAL_NOT_ALLOWED`. Единственный согласующий (автор на всех шагах) — по-прежнему
автосогласование. D-11: суперпользователь закрывает шаг за другого — разрешено, но журнал помечает «от имени».
"""

# flake8: noqa: F811  (фикстуры импортируются из соседних тестов и подставляются аргументами)

import pytest

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


def _reviewer_author(seller):
    """Автор КП, который сам держит quote.build и quote.review (ВЭД, собирающий КП)."""
    role = CompanyRole.objects.create(
        company=seller["company"],
        name="ВЭД-автор",
        permissions=[Permission.QUOTE_BUILD.value, Permission.QUOTE_REVIEW.value],
    )
    author = _user("ved-author@seller.test")
    _member(seller["company"], author, workspace_role="MEMBER", company_roles=[role])
    return author


def _other_reviewer(seller, email="ved2@seller.test"):
    role = CompanyRole.objects.create(
        company=seller["company"], name=f"ВЭД {email}", permissions=[Permission.QUOTE_REVIEW.value]
    )
    user = _user(email)
    _member(seller["company"], user, workspace_role="MEMBER", company_roles=[role])
    return user


def test_author_is_not_a_reviewer_of_own_quote(seller, deal):
    author = _reviewer_author(seller)
    other = _other_reviewer(seller)
    quote = _quote(deal, prepared_by=author)

    _, err = QLS.submit_for_review(quote.id, author)

    assert err is None
    reviewer_steps = quote.approval_steps.filter(participation=StepParticipation.APPROVER)
    assert [step.approver.user_id for step in reviewer_steps] == [other.id]


def test_preview_excludes_author_from_reviewers(seller, deal):
    author = _reviewer_author(seller)
    other = _other_reviewer(seller)
    quote = _quote(deal, prepared_by=author)

    preview, err = preview_approval_chain(quote.id, author)

    assert err is None
    reviewer_user_ids = [s["user_id"] for s in preview["steps"] if s["trigger"] == StepTrigger.TRADE_REVIEW]
    assert reviewer_user_ids == [other.id]


def test_author_cannot_act_on_approver_step(seller, deal):
    """Шаг APPROVER на имя автора (старая цепочка / роль выдана позже) автор закрыть не может."""
    author = _reviewer_author(seller)
    quote = _quote(deal, prepared_by=author)
    _other_reviewer(seller)
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

    author = _reviewer_author(seller)
    quote = _quote(deal, prepared_by=author)
    _other_reviewer(seller)
    QLS.submit_for_review(quote.id, author)
    step = quote.approval_steps.get(participation=StepParticipation.APPROVER)
    QuoteApprovalStep.objects.filter(pk=step.pk).update(approver=author.memberships.get(company=seller["company"]))

    response = _api(author).post(
        f"/api/v1/crm/quotes/{quote.id}/approval-act/", {"step_id": step.id, "decision": "APPROVE"}, format="json"
    )

    assert response.status_code == 403, response.content
    assert response.json()["detail"] == "SELF_APPROVAL_NOT_ALLOWED"


def test_solo_author_chain_still_auto_approves(seller, deal):
    """Единственный согласующий — сам автор (руководитель собрал КП): автосогласование работает."""
    head = seller["head"]
    quote = _quote(deal, prepared_by=head)

    _, err = QLS.submit_for_review(quote.id, head)

    assert err is None
    assert _status(quote) == "READY_TO_SEND"


def test_another_head_is_preferred_over_the_author(seller, deal):
    """Автор-руководитель при втором руководителе не согласует сам себя: шаг HEAD идёт другому."""
    second_head = _user("head2@seller.test")
    _member(seller["company"], second_head, workspace_role="MEMBER", company_roles=[seller["admin_role"]])
    quote = _quote(deal, prepared_by=seller["head"])

    QLS.submit_for_review(quote.id, seller["head"])

    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    assert head_step.approver.user_id == second_head.id
    assert _status(quote) == "PENDING_APPROVAL"


def test_superuser_acting_for_the_approver_is_marked_on_behalf(seller, deal):
    admin = _user("root@seller.test")
    admin.is_superuser = True
    admin.save(update_fields=["is_superuser"])
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)

    _, err = act_on_step(head_step.id, admin, "APPROVE")

    assert err is None and _status(quote) == "READY_TO_SEND"
    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_approved").latest("id")
    assert event.user_id == admin.id
    assert event.event_params["on_behalf_of_user_id"] == seller["head"].id
    assert "head@seller.test" in event.event_params["on_behalf_of"]
    assert "от имени" in event.detail


def test_superuser_rejecting_for_the_approver_is_marked_on_behalf(seller, deal):
    admin = _user("root2@seller.test")
    admin.is_superuser = True
    admin.save(update_fields=["is_superuser"])
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)

    act_on_step(head_step.id, admin, "REJECT", comment="нет")

    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_rejected").latest("id")
    assert event.event_params["on_behalf_of_user_id"] == seller["head"].id
    assert event.event_params["comment"] == "нет"


def test_regular_approver_is_not_marked_on_behalf(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)

    act_on_step(head_step.id, seller["head"], "APPROVE")

    event = ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.approval_step_approved").latest("id")
    assert "on_behalf_of" not in event.event_params
