"""СЦ-9 (решение владельца 2026-11-21): акт выпускается после доставки.

Правило одно (`billing.act_not_delivered`): исполнение «Доставлено» или «Принято клиентом». Карточка проекта отдаёт
`act_blocker = not_delivered`, сервер отказывает выпуску с 409 `ACT_NOT_DELIVERED`.
"""

import pytest
from integration.tests import world as w

from crm.constants import ContractStatusCode as S
from crm.constants import InvoiceStatusCode
from crm.tests.delivery_support import mark_delivered
from crm.tests.projects_world import api, contract_in, pw  # noqa: F401

pytestmark = pytest.mark.django_db


def _paid_invoice(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    return w.add_invoice(pw.deal, InvoiceStatusCode.PAID, total="5", paid="5", contract=contract)


def _issue(pw, invoice):  # noqa: F811
    return api(pw.accountant).post(f"/api/v1/crm/invoices/{invoice.id}/generate-act/")


@pytest.mark.parametrize("status", [None, "PENDING", "SHIPPED", "IN_TRANSIT", "DISPUTED"])
def test_act_is_refused_before_delivery(pw, status):  # noqa: F811
    invoice = _paid_invoice(pw)
    if status:
        w.add_fulfillment(pw.deal, status)
    response = _issue(pw, invoice)
    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "ACT_NOT_DELIVERED"


@pytest.mark.parametrize("status", ["DELIVERED", "ACCEPTED"])
def test_act_is_issued_once_delivered_or_accepted(pw, status):  # noqa: F811
    invoice = _paid_invoice(pw)
    mark_delivered(pw.deal, status)
    assert _issue(pw, invoice).status_code == 201


def test_existing_act_is_still_reported_as_existing_before_delivery_check(pw):  # noqa: F811
    invoice = _paid_invoice(pw)
    mark_delivered(pw.deal)
    assert _issue(pw, invoice).status_code == 201
    assert _issue(pw, invoice).json()["detail"].startswith("ACT_ALREADY_EXISTS")
