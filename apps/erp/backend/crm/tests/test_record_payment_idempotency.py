"""FIX-55 / D-05: повтор `record-payment` с тем же референсом.

Тот же референс + та же сумма и дата — повтор, возвращается существующий платёж (200, деньги не
дублируются; в том числе когда первый платёж уже закрыл счёт). Тот же референс с другой суммой или
датой — 409 `PAYMENT_REFERENCE_CONFLICT`, сумма не теряется молча (раньше возвращался прежний платёж с 201).
"""

from decimal import Decimal

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from crm.models import Payment
from crm.tests.test_record_payment_back_office import world  # noqa: F401


def _pay(user, invoice, **body):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    payload = {"amount": "50.00", "paid_at": "2026-10-14", "reference": "BANK-7"}
    payload.update(body)
    return client.post(f"/api/v1/crm/invoices/{invoice.id}/record-payment/", payload, format="json")


def test_first_payment_is_created(world):  # noqa: F811
    response = _pay(world["finance"], world["invoice"])
    assert response.status_code == 201, response.content


def test_same_reference_same_amount_returns_existing_payment(world):  # noqa: F811
    first = _pay(world["finance"], world["invoice"])
    second = _pay(world["finance"], world["invoice"])

    assert second.status_code == 200, second.content
    assert second.json()["id"] == first.json()["id"]
    assert Payment.objects.filter(invoice=world["invoice"]).count() == 1
    world["invoice"].refresh_from_db()
    assert world["invoice"].amount_paid == Decimal("50.00")


def test_replay_of_a_payment_that_closed_the_invoice_is_still_a_replay(world):  # noqa: F811
    """Счёт закрыт первым платежом: повтор с тем же референсом — не INVOICE_ALREADY_PAID, а тот же платёж."""
    first = _pay(world["finance"], world["invoice"], amount="112.00")
    second = _pay(world["finance"], world["invoice"], amount="112.00")

    assert first.status_code == 201, first.content
    assert second.status_code == 200, second.content
    assert second.json()["id"] == first.json()["id"]


def test_same_reference_other_amount_is_conflict(world):  # noqa: F811
    _pay(world["finance"], world["invoice"])
    response = _pay(world["finance"], world["invoice"], amount="60.00")

    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "PAYMENT_REFERENCE_CONFLICT"
    assert Payment.objects.filter(invoice=world["invoice"]).count() == 1
    world["invoice"].refresh_from_db()
    assert world["invoice"].amount_paid == Decimal("50.00")


def test_same_reference_other_date_is_conflict(world):  # noqa: F811
    _pay(world["finance"], world["invoice"])
    response = _pay(world["finance"], world["invoice"], paid_at="2026-10-15")

    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "PAYMENT_REFERENCE_CONFLICT"


def test_conflict_after_the_invoice_is_paid_is_still_conflict(world):  # noqa: F811
    """Счёт закрыт; тот же референс с другой суммой — конфликт, а не «счёт уже оплачен»."""
    _pay(world["finance"], world["invoice"], amount="112.00")
    response = _pay(world["finance"], world["invoice"], amount="10.00")

    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "PAYMENT_REFERENCE_CONFLICT"


def test_other_reference_is_a_new_payment(world):  # noqa: F811
    _pay(world["finance"], world["invoice"])
    response = _pay(world["finance"], world["invoice"], reference="BANK-8", amount="20.00")

    assert response.status_code == 201, response.content
    assert Payment.objects.filter(invoice=world["invoice"]).count() == 2
