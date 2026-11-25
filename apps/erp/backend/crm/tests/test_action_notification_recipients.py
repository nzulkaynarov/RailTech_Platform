# flake8: noqa: F811  (fixtures `world`/`lookups` are imported from test_post_contract_emails)
"""СОТР-1: уведомления «пора действовать» идут тем, кто может действовать, а не всем продавцам.

Черновик счёта — держателям `finance.invoice` (бухгалтер) и ответственному продавцу; отказ заказчика по акту —
держателям `fulfillment.act` и ответственному продавцу. Остальные продавцы их не получают.
"""

from unittest.mock import patch

import pytest

from accounts.models import CompanyRole
from accounts.testing import make_own_company
from crm.services import deal_notifications as dn
from crm.services.invoice_lifecycle import notify_seller_invoice_draft
from crm.tests.test_post_contract_emails import _invoice, _member, lookups, world  # noqa: F401,F811  (fixtures)
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _with_role(world, email, permission):
    user = _member(world["seller_co"], email, can_sell=True)
    role = CompanyRole.objects.create(company=world["seller_co"], name=f"Роль {email}", permissions=[permission])
    user.memberships.get(company=world["seller_co"]).company_roles.add(role)
    return user


@pytest.fixture
def team(world, settings):
    make_own_company(world["seller_co"])
    settings.OWN_COMPANY_ID = world["seller_co"].pk
    deal = world["deal"]
    deal.manager = world["seller_user"]  # ответственный продавец
    deal.save(update_fields=["manager"])
    other_seller = _member(world["seller_co"], "other-seller@g3.test", can_sell=True)
    return {
        "accountant": _with_role(world, "accountant@g3.test", "finance.invoice"),
        "executor": _with_role(world, "executor@g3.test", "fulfillment.act"),
        "other_seller": other_seller,
    }


def _got(user, event_code):
    return Notification.objects.filter(user=user, event_code=event_code).exists()


def test_invoice_draft_goes_to_finance_invoice_holders_and_the_responsible_seller(world, team):
    invoice = _invoice(world, "DRAFT")
    with patch("notifications.tasks.send_transactional_email"):
        notify_seller_invoice_draft(invoice)
    assert _got(team["accountant"], "invoice.draft_created")
    assert _got(world["seller_user"], "invoice.draft_created")
    assert not _got(team["other_seller"], "invoice.draft_created")
    assert not _got(team["executor"], "invoice.draft_created")


def test_act_rejection_goes_to_fulfillment_act_holders_and_the_responsible_seller(
    world, team, django_capture_on_commit_callbacks
):
    from decimal import Decimal

    from accounts.testing import make_cashier  # noqa: F401
    from crm.services.billing import generate_act
    from crm.tests.delivery_support import mark_delivered

    paid = _invoice(world, "PAID", paid=Decimal("112"))
    with patch("notifications.tasks.send_transactional_email"):
        with django_capture_on_commit_callbacks(execute=True):
            mark_delivered(paid.deal)
            act, error = generate_act(paid.id, actor=world["seller_user"])
        assert error is None, error
        dn.notify_act_rejected(act, world["buyer_user"], "Неверная сумма")
    assert _got(team["executor"], "act.rejected")
    assert _got(world["seller_user"], "act.rejected")
    assert not _got(team["other_seller"], "act.rejected")
    assert not _got(team["accountant"], "act.rejected")
