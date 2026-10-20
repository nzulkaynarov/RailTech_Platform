"""Зеркальная сделка ERP: какие поля правит только бэк-офис (I-26, хвост FIX-34)."""

from decimal import Decimal

import pytest

from app.domain.deals import ERP_OWNED_FIELDS, erp_owned_changes

CURRENT = {
    "title": "Заявка: Ромашка",
    "amount": Decimal("1000.00"),
    "currency": "UZS",
    "stage": "open",
    "lost_reason": None,
}


def test_fields_the_erp_event_receiver_writes_are_erp_owned() -> None:
    # Приёмник событий пишет название, сумму, валюту, стадию и причину отказа (`erp_events`,
    # `erp_event_handlers._outcome`); поля CRM (ответственный, срок, продукт) в списке не значатся.
    assert {"title", "amount", "currency", "stage", "lost_reason"} == ERP_OWNED_FIELDS


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ({"amount": Decimal("5")}, ["amount"]),
        ({"amount": None}, ["amount"]),
        ({"currency": "USD"}, ["currency"]),
        ({"stage": "won"}, ["stage"]),
        ({"title": "Другое"}, ["title"]),
        ({"lost_reason": "Дорого"}, ["lost_reason"]),
        ({"amount": Decimal("5"), "stage": "lost"}, ["amount", "stage"]),
        # Те же значения, что уже в зеркале, — не изменение (форма шлёт поля целиком).
        ({"amount": Decimal("1000"), "currency": "UZS", "stage": "open"}, []),
        # Поля CRM.
        ({"owner_user_id": 7, "expected_close_date": None, "product_key": "wagons"}, []),
        ({}, []),
    ],
)
def test_only_real_changes_of_erp_owned_fields_are_reported(
    requested: dict[str, object], expected: list[str]
) -> None:
    assert erp_owned_changes(CURRENT, requested) == expected
