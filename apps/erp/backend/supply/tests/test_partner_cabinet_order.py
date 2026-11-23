"""ДК-5: заказ поставщику у партнёра с Кабинетом — одно письмо со ссылкой и «подтверждён» только когда подтвердил он сам.

* уходит одно письмо — уведомление со ссылкой на заказ; письмо «подтвердите ответом» тем, кто подтверждает в Кабинете, не шлём;
* партнёр без Кабинета (или без контакта с правом подтверждать) — прежнее письмо, и сотрудник записывает его подтверждение;
* с Кабинетом сотрудник не ставит «подтверждён» за партнёра: 409 `PARTNER_CONFIRMS_IN_CABINET`, кнопки в `actions` нет;
* подтвердил сам партнёр в Кабинете — статус `confirmed` и в журнале «Подтверждён поставщиком».
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.utils import timezone
from inventory.tests.support import api
from parties.models import CompanyRelationship, Contact
from portal.models import PortalNotice
from supply.models import SupplierOrder
from supply.tests.test_orders import (  # noqa: F401 — autouse: только локальная почта
    _act,
    _create,
    _tomorrow,
    locmem_mail,
)

from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _cabinet_partner(world, *, can_act=True, invited=True, modules=("my_products",)):
    CompanyRelationship.objects.create(
        company=world["vendor"], role="partner", status="active", modules=list(modules), activated_at=timezone.now()
    )
    return Contact.objects.create(
        company=world["vendor"],
        name="Dilshod",
        email="dilshod@vendor.example",
        language="ru",
        can_act=can_act,
        invited_at=timezone.now() if invited else None,
    )


def _draft(world):
    return _create(
        world,
        expected_date=_tomorrow(),
        lines=[{"product_id": world["rail"].pk, "quantity": 3, "unit_price": "100.00"}],
    ).json()


def _letters_about(order) -> list:
    """Все письма, которые партнёр получает по этому заказу: письмо процесса и письма-уведомления контактам."""
    process = list(EmailLog.objects.filter(template="supplier_order"))
    notices = list(PortalNotice.objects.filter(kind="partner_order_sent", object_id=order["id"], channel="email"))
    return process + notices


def test_cabinet_partner_gets_one_letter_with_the_link(world):
    contact = _cabinet_partner(world)
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200

    letters = _letters_about(order)
    assert len(letters) == 1, "одно письмо на заказ"
    notice = letters[0]
    assert isinstance(notice, PortalNotice) and notice.contact_id == contact.pk
    assert notice.link == f"/partner/orders?orderId={order['id']}"
    assert not EmailLog.objects.filter(
        template="supplier_order"
    ).exists(), "письма «ответьте на это» партнёру с Кабинетом нет"
    assert mail.outbox == [] or all("supplier_order" not in m.subject for m in mail.outbox)


def test_partner_without_a_cabinet_gets_the_old_letter_and_staff_records_the_confirmation(world):
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200
    assert len(_letters_about(order)) == 1 and EmailLog.objects.filter(template="supplier_order").count() == 1
    confirmed = _act(world, order["id"], "confirm", {"expected_date": _tomorrow()})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"


def _send_to(world, order, address):
    from inventory.tests.support import complete_order

    complete_order(order["id"])
    sent = api(world["supply"]).post(f"{STOCK}orders/{order['id']}/send/", {"to_email": address}, format="json")
    assert sent.status_code == 200, sent.json()


def test_explicit_contact_address_gets_the_link_letter_only(world):
    _cabinet_partner(world)
    order = _draft(world)
    _send_to(world, order, "dilshod@vendor.example")
    letters = _letters_about(order)
    assert len(letters) == 1 and isinstance(letters[0], PortalNotice), "тот же адрес — одно письмо со ссылкой"
    assert not EmailLog.objects.filter(template="supplier_order").exists()


def test_explicit_foreign_address_never_asks_to_reply_while_the_cabinet_confirms(world):
    _cabinet_partner(world)
    order = _draft(world)
    _send_to(world, order, "office@vendor.example")
    assert EmailLog.objects.filter(template="supplier_order").count() == 1
    letter = next(m for m in mail.outbox if m.to == ["office@vendor.example"])
    assert "ответом на это письмо" not in letter.body
    assert "личном кабинете партнёра" in letter.body
    assert api(world["supply"]).get(f"{STOCK}orders/{order['id']}/").json()["actions"]["confirm"] is False


def test_contact_who_turned_order_mail_off_does_not_trigger_the_reply_letter(world):
    contact = _cabinet_partner(world)
    contact.notification_settings = {"partner_products": {"email": False}}
    contact.save()
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200
    assert not EmailLog.objects.filter(
        template="supplier_order"
    ).exists(), "письма «ответьте» нет, пока подтверждает Кабинет"
    assert api(world["supply"]).get(f"{STOCK}orders/{order['id']}/").json()["actions"]["confirm"] is False


def test_contact_without_the_right_gets_no_confirm_notice(world):
    _cabinet_partner(world, can_act=False)
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200
    assert not PortalNotice.objects.filter(kind="partner_order_sent", object_id=order["id"]).exists()
    assert EmailLog.objects.filter(template="supplier_order").count() == 1, "подтверждает сотрудник — прежнее письмо"


def test_mail_state_of_a_cabinet_partner_comes_from_the_notice(world):
    from portal.models import NoticeEmailState

    _cabinet_partner(world)
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200
    url = f"{STOCK}orders/{order['id']}/"
    notice = PortalNotice.objects.get(kind="partner_order_sent", object_id=order["id"])
    for state, expected in (
        (NoticeEmailState.PENDING, "queued"),
        (NoticeEmailState.SENT, "sent"),
        (NoticeEmailState.FAILED, "failed"),
    ):
        PortalNotice.objects.filter(pk=notice.pk).update(email_state=state, email_reason="rejected: no mailbox")
        mail_state = api(world["supply"]).get(url).json()["mail"]
        assert mail_state and mail_state["state"] == expected, (state, mail_state)


def test_staff_cannot_confirm_for_a_partner_who_confirms_in_the_cabinet(world):
    _cabinet_partner(world)
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200

    detail = api(world["supply"]).get(f"{STOCK}orders/{order['id']}/").json()
    assert detail["actions"]["confirm"] is False

    refused = _act(world, order["id"], "confirm", {"expected_date": _tomorrow()})
    assert refused.status_code == 409 and refused.json()["detail"] == "PARTNER_CONFIRMS_IN_CABINET", refused.json()
    assert SupplierOrder.objects.get(pk=order["id"]).status == "sent"


@pytest.mark.parametrize(
    "kwargs",
    [{"can_act": False}, {"invited": False}, {"modules": ("catalog_requests",)}],
    ids=["no-right", "not-invited", "no-orders-section"],
)
def test_partner_who_cannot_confirm_in_the_cabinet_is_confirmed_by_staff(world, kwargs):
    _cabinet_partner(world, **kwargs)
    order = _draft(world)
    assert _act(world, order["id"], "send").status_code == 200
    assert api(world["supply"]).get(f"{STOCK}orders/{order['id']}/").json()["actions"]["confirm"] is True
    assert _act(world, order["id"], "confirm", {"expected_date": _tomorrow()}).status_code == 200
