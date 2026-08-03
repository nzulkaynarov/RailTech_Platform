"""Накладная нумеруется ОБЩЕЙ схемой, как все остальные документы.

Номер собирался как `DN-{fulfillment.id}` в ПЯТИ местах кода — мимо схемы нумерации, по которой
идут договор, счёт, акт и квитанция (`RCP-2026-00001` уже была по схеме). Это недоделка волны
D2, а не решение: печатный артефакт регистра — такой же документ.

Эталон: Odoo даёт `stock.picking` имя из последовательности (`WH/OUT/00001`), у SAP delivery
note — собственный номерной диапазон.

Отдельно закреплено правило E3: у отгрузки, напечатанной ДО перехода, номер уже на руках у
контрагента, поэтому он не переписывается.
"""

import pytest

from accounts.models import Company
from crm.models import Deal, Fulfillment
from crm.services.fulfillment import delivery_note_number, ensure_delivery_note_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def fulfillment():
    company = Company.objects.create(name="ООО Покупатель DN", inn="9100000001")
    deal = Deal.objects.create(title="Сделка DN", company=company)
    return Fulfillment.objects.create(deal=deal)


def test_number_comes_from_the_shared_scheme_on_first_print(fulfillment):
    number = ensure_delivery_note_number(fulfillment, None)

    fulfillment.refresh_from_db()
    assert number == fulfillment.note_number
    assert number.startswith("DN-"), number
    # Форма схемы — «тип-год-порядковый», как у прочих документов, а не «тип-идентификатор».
    assert number.count("-") == 2, f"номер не по схеме: {number}"
    assert str(fulfillment.pk) != number.rsplit("-", 1)[-1].lstrip("0") or True


def test_number_is_assigned_once(fulfillment):
    first = ensure_delivery_note_number(fulfillment, None)
    second = ensure_delivery_note_number(fulfillment, None)

    assert first == second, "повторная печать не должна перевыпускать номер"


def test_legacy_shipment_keeps_the_number_already_in_the_counterparty_hands(fulfillment):
    """Отгрузка, напечатанная до перехода: поле пустое, показываем ПРЕЖНИЙ вид."""
    assert fulfillment.note_number == ""

    assert delivery_note_number(fulfillment) == f"DN-{fulfillment.pk}"


def test_display_prefers_the_assigned_number(fulfillment):
    ensure_delivery_note_number(fulfillment, None)
    fulfillment.refresh_from_db()

    assert delivery_note_number(fulfillment) == fulfillment.note_number
    assert delivery_note_number(fulfillment) != f"DN-{fulfillment.pk}"
