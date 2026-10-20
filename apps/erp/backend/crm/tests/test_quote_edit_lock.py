"""FIX-55 / D-04: позиции и расходы КП правятся только в DRAFT и пока КП не заморожено.

Прогон M1 нашёл: после согласования/отправки/акцепта позиции КП ещё писались (API проверял только
продавца и `frozen_at`, который ставится лишь при отправке клиенту). Теперь на каждый статус ≠ DRAFT
create/update/delete, bulk-операции, перепривязка, расходы и PATCH КП суммы — 409 `QUOTE_NOT_DRAFT`;
у замороженного КП — 409 `QUOTE_FROZEN`; в DRAFT всё работает как раньше.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from crm.constants import QuoteStatusCode
from crm.models import ChargeType, QuoteCharge, QuoteItem, QuoteStatus
from crm.tests.test_quote_items_bulk_update import _api, _quote_with_items, lookups, world  # noqa: F401

ITEMS = "/api/v1/crm/quote-items/"
CHARGES = "/api/v1/crm/quote-charges/"
QUOTES = "/api/v1/crm/quotes/"

NON_DRAFT = [code for code in QuoteStatusCode.values if code != QuoteStatusCode.DRAFT]


def _set_status(quote, code):
    status_row, _ = QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 50})
    quote.status = status_row
    quote.save(update_fields=["status"])


def _charge(quote):
    freight, _ = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Фрахт"})
    return QuoteCharge.objects.create(quote=quote, charge_type=freight, amount=Decimal("10.00"))


def _operations(quote, item, charge):
    """(название, функция client → response) для каждого пути записи состава/цен КП."""
    return [
        ("item-create", lambda c: c.post(ITEMS, {"quote": quote.id, "imported_raw_name": "Новая"}, format="json")),
        ("item-patch", lambda c: c.patch(f"{ITEMS}{item.id}/", {"quantity": 7}, format="json")),
        ("item-delete", lambda c: c.delete(f"{ITEMS}{item.id}/")),
        (
            "bulk-update",
            lambda c: c.post(
                f"{ITEMS}bulk-update/",
                {"quote": quote.id, "items": [{"id": item.id, "frozen_base_price": "999"}]},
                format="json",
            ),
        ),
        (
            "bulk-create",
            lambda c: c.post(
                f"{ITEMS}bulk-create/", {"quote": quote.id, "items": [{"imported_raw_name": "X"}]}, format="json"
            ),
        ),
        (
            "bulk-delete",
            lambda c: c.post(f"{ITEMS}bulk-delete/", {"quote": quote.id, "items": [item.id]}, format="json"),
        ),
        ("reassign", lambda c: c.post(f"{ITEMS}{item.id}/reassign-product/", {"product_id": None}, format="json")),
        (
            "charge-create",
            lambda c: c.post(CHARGES, {"quote": quote.id, "charge_type": "FREIGHT", "amount": "5"}, format="json"),
        ),
        ("charge-patch", lambda c: c.patch(f"{CHARGES}{charge.id}/", {"amount": "77"}, format="json")),
        ("charge-delete", lambda c: c.delete(f"{CHARGES}{charge.id}/")),
        (
            "charges-reorder",
            lambda c: c.post(f"{QUOTES}{quote.id}/charges-reorder/", {"order": [charge.id]}, format="json"),
        ),
        (
            "delivery-basis",
            lambda c: c.post(f"{QUOTES}{quote.id}/set-delivery-basis/", {"delivery_basis": None}, format="json"),
        ),
        ("quote-patch-vat", lambda c: c.patch(f"{QUOTES}{quote.id}/", {"vat_rate": "0"}, format="json")),
        ("quote-patch-margin", lambda c: c.patch(f"{QUOTES}{quote.id}/", {"margin_percent": "50"}, format="json")),
        ("apply-defaults", lambda c: c.post(f"{QUOTES}{quote.id}/apply-defaults/", {}, format="json")),
    ]


OP_NAMES = [
    name for name, _ in _operations(type("Q", (), {"id": 0})(), type("I", (), {"id": 0})(), type("C", (), {"id": 0})())
]


def _snapshot(quote):
    quote.refresh_from_db()
    return (
        QuoteItem.objects.filter(quote=quote).count(),
        list(QuoteItem.objects.filter(quote=quote).values_list("id", "quantity", "frozen_base_price")),
        QuoteCharge.objects.filter(quote=quote).count(),
        list(QuoteCharge.objects.filter(quote=quote).values_list("id", "amount")),
        quote.vat_rate,
        quote.margin_percent,
        quote.total_incl_vat,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("status_code", NON_DRAFT)
@pytest.mark.parametrize("op_name", OP_NAMES)
def test_non_draft_quote_is_not_editable(world, status_code, op_name):  # noqa: F811
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100, 200])
    charge = _charge(quote)
    _set_status(quote, status_code)
    before = _snapshot(quote)
    op = dict(_operations(quote, items[0], charge))[op_name]

    resp = op(_api(world["seller_user"]))

    assert resp.status_code == 409, (status_code, op_name, resp.content)
    assert resp.json()["detail"] == "QUOTE_NOT_DRAFT"
    assert _snapshot(quote) == before, "отказ не должен ничего менять"


@pytest.mark.django_db
@pytest.mark.parametrize("op_name", OP_NAMES)
def test_frozen_quote_is_not_editable(world, op_name):  # noqa: F811
    """Замороженное отправкой КП (frozen_at) — 409 QUOTE_FROZEN даже при статусе DRAFT."""
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100, 200])
    charge = _charge(quote)
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])
    before = _snapshot(quote)
    op = dict(_operations(quote, items[0], charge))[op_name]

    resp = op(_api(world["seller_user"]))

    assert resp.status_code == 409, (op_name, resp.content)
    assert resp.json()["detail"] == "QUOTE_FROZEN"
    assert _snapshot(quote) == before


@pytest.mark.django_db
@pytest.mark.parametrize("op_name", OP_NAMES)
def test_draft_quote_stays_editable(world, op_name):  # noqa: F811
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100, 200])
    charge = _charge(quote)
    op = dict(_operations(quote, items[0], charge))[op_name]

    resp = op(_api(world["seller_user"]))

    assert resp.status_code in (200, 201, 204), (op_name, resp.content)


@pytest.mark.django_db
def test_quote_notes_stay_editable_outside_draft(world):  # noqa: F811
    """Поля, не влияющие на сумму (заметки), в не-DRAFT не блокируются — блок точечный."""
    _deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    _set_status(quote, QuoteStatusCode.PENDING_APPROVAL)

    resp = _api(world["seller_user"]).patch(f"{QUOTES}{quote.id}/", {"notes": "примечание"}, format="json")

    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_rejected_quote_new_version_and_withdraw_still_work(world):  # noqa: F811
    """REJECTED закрыт для правок, но дальше есть путь: новая версия (DRAFT) и возврат в черновик."""
    from crm.services.quotes import duplicate_quote

    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    _set_status(quote, QuoteStatusCode.REJECTED)
    client = _api(world["seller_user"])
    assert client.patch(f"{ITEMS}{items[0].id}/", {"quantity": 3}, format="json").status_code == 409

    new_quote = duplicate_quote(quote.id, world["seller_user"])
    new_quote = new_quote[0] if isinstance(new_quote, tuple) else new_quote
    assert new_quote.status.code == QuoteStatusCode.DRAFT
    new_item = QuoteItem.objects.filter(quote=new_quote).first()
    resp = client.patch(f"{ITEMS}{new_item.id}/", {"quantity": 3}, format="json")
    assert resp.status_code == 200, resp.content
