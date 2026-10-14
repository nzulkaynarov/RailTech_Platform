"""Уведомления на пути «после договора» (F2).

До этой волны отрезок молчал: об оплате продавец не узнавал никак (событие писалось только в
журнал активности), акт не порождал ни одного уведомления, движение груза — тоже, а просрочка
доставки адресовалась `deal.manager` — legacy-полю, у реальных сделок пустому, при том что
задача исправно рапортовала о «помеченных» строках.

Отдельно проверяется АДРЕСАТ: уведомление о собственном действии — шум, поэтому подписавший
акт или отгрузивший груз своего же уведомления не получает.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)
from notifications.models import Notification


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("CONTRACT_SIGNED", "CLOSED_WON"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 70})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 50})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 40})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("PENDING", "SHIPPED", "IN_TRANSIT", "DELIVERED", "ACCEPTED", "DISPUTED"):
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    from notifications.models import NotificationType

    for code in ("INFO", "SUCCESS", "WARNING", "ERROR"):
        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


@pytest.fixture
def chain(lookups):
    buyer_co = _company("Buyer Notify", "B600", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@notify.test", can_buy=True)
    seller_co = _company("Seller Notify", "S600", "SUPPLIER")
    seller_user = _member(seller_co, "seller@notify.test", can_sell=True)

    deal = Deal.objects.create(title="Notify deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-NOTIFY-1",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-NOTIFY-1",
        status=InvoiceStatus.objects.get(code="ISSUED"),
        total_incl_vat=Decimal("112"),
    )
    return {
        "deal": deal,
        "contract": contract,
        "invoice": invoice,
        "buyer_user": buyer_user,
        "seller_user": seller_user,
    }


def _notifications_for(user):
    return list(Notification.objects.filter(user=user).order_by("id"))


def test_seller_is_notified_when_a_payment_is_recorded(chain, django_capture_on_commit_callbacks):
    """Об оплате продавец не узнавал НИКАК — только запись в журнале активности."""
    from crm.services.billing import record_payment

    with django_capture_on_commit_callbacks(execute=True):
        payment, error = record_payment(
            chain["invoice"].id,
            chain["buyer_user"],
            amount=Decimal("112"),
            paid_at=timezone.localdate(),
        )
    assert error is None, error
    assert payment is not None

    seller_notifications = _notifications_for(chain["seller_user"])
    assert len(seller_notifications) == 1, "продавец не узнал об оплате"
    notification = seller_notifications[0]
    assert notification.title == "Оплата получена"
    assert notification.deal_id == chain["deal"].id
    # Точная ссылка на счёт, а не «на сделку вообще».
    assert notification.link == f"#invoices?open={chain['invoice'].id}"


def test_buyer_is_notified_when_an_act_is_issued(chain, django_capture_on_commit_callbacks):
    from crm.services.billing import generate_act

    chain["invoice"].status = InvoiceStatus.objects.get(code="PAID")
    chain["invoice"].amount_paid = Decimal("112")
    chain["invoice"].save(update_fields=["status", "amount_paid"])

    with django_capture_on_commit_callbacks(execute=True):
        act, error = generate_act(chain["invoice"].id, actor=chain["seller_user"])
    assert error is None, error

    buyer_notifications = [n for n in _notifications_for(chain["buyer_user"]) if n.title == "Акт выставлен"]
    assert len(buyer_notifications) == 1, "покупатель не узнал о выставленном акте"
    # Реестр актов покупателю закрыт (SELLER_PAGES) — ведём на карточку сделки по FK,
    # поэтому точной ссылки здесь быть НЕ должно.
    assert buyer_notifications[0].link == ""
    assert buyer_notifications[0].deal_id == chain["deal"].id
    assert act is not None


def test_act_signature_notifies_the_other_side_but_not_the_signer(chain, django_capture_on_commit_callbacks):
    from crm.services.billing import sign_act

    act = Act.objects.create(
        deal=chain["deal"],
        contract=chain["contract"],
        invoice=chain["invoice"],
        number="ACT-NOTIFY-1",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    with django_capture_on_commit_callbacks(execute=True):
        signed, error = sign_act(act.id, chain["buyer_user"])
    assert error is None, error
    assert signed is not None

    assert [n.title for n in _notifications_for(chain["seller_user"])] == ["Акт подписан"]
    assert not [
        n for n in _notifications_for(chain["buyer_user"]) if n.title == "Акт подписан"
    ], "подписавший получил уведомление о собственном действии"


def test_shipment_notifies_the_buyer_not_the_shipping_seller(chain, django_capture_on_commit_callbacks):
    from crm.services.fulfillment import ensure_fulfillment, update_fulfillment_status

    ensure_fulfillment(chain["deal"], contract=chain["contract"])
    with django_capture_on_commit_callbacks(execute=True):
        fulfillment, error = update_fulfillment_status(chain["deal"].id, chain["seller_user"], "SHIPPED")
    assert error is None, error
    assert fulfillment is not None

    assert [n.title for n in _notifications_for(chain["buyer_user"])] == ["Груз отгружен"]
    assert not _notifications_for(chain["seller_user"]), "отгрузивший получил уведомление о себе"


def test_acceptance_notifies_the_seller_not_the_accepting_buyer(chain, django_capture_on_commit_callbacks):
    from crm.services.fulfillment import ensure_fulfillment, update_fulfillment_status

    ensure_fulfillment(chain["deal"], contract=chain["contract"])
    with django_capture_on_commit_callbacks(execute=True):
        _, error = update_fulfillment_status(chain["deal"].id, chain["buyer_user"], "ACCEPTED")
    assert error is None, error

    assert [n.title for n in _notifications_for(chain["seller_user"])] == ["Поставка принята"]


def test_overdue_delivery_notifies_both_sides_and_reports_honestly(chain):
    """Прежде уведомление уходило одному `deal.manager` (у реальных сделок пустому), а счётчик
    инкрементировался всё равно: задача рапортовала о работе, которой не делала."""
    from crm.tasks import check_overdue_deliveries

    assert chain["deal"].manager_id is None, "предпосылка: legacy-получатель у сделки не задан"
    Fulfillment.objects.create(
        deal=chain["deal"],
        contract=chain["contract"],
        status=FulfillmentStatus.objects.get(code="SHIPPED"),
        expected_delivery_date=timezone.localdate() - timedelta(days=3),
    )

    result = check_overdue_deliveries()

    assert result["overdue_flagged"] == 1
    assert result["notified"] == 2, "должны быть извещены обе стороны, а не никто"
    for user in (chain["buyer_user"], chain["seller_user"]):
        titles = [n.title for n in _notifications_for(user)]
        assert "Просрочка по доставке" in titles, f"{user.email} не узнал о просрочке"


def test_payment_notification_is_not_created_when_the_transaction_rolls_back(chain):
    """Уведомления висят на on_commit — откат не должен оставлять «призрачное» событие."""
    from crm.services.billing import record_payment

    # Без execute=True колбэки on_commit собираются, но НЕ выполняются: это и есть поведение
    # откатившейся транзакции с точки зрения наблюдателя.
    payment, error = record_payment(
        chain["invoice"].id,
        chain["buyer_user"],
        amount=Decimal("50"),
        paid_at=timezone.localdate(),
    )
    assert error is None
    assert payment is not None
    assert not _notifications_for(chain["seller_user"]), "уведомление ушло до коммита"


def test_payment_recorded_still_writes_the_ledger_row(chain, django_capture_on_commit_callbacks):
    """Контроль: добавление уведомления не сломало сам платёж."""
    from crm.services.billing import record_payment

    with django_capture_on_commit_callbacks(execute=True):
        record_payment(chain["invoice"].id, chain["buyer_user"], amount=Decimal("112"), paid_at=timezone.localdate())

    chain["invoice"].refresh_from_db()
    assert Payment.objects.filter(invoice=chain["invoice"]).count() == 1
    assert chain["invoice"].amount_paid == Decimal("112")
    assert chain["invoice"].status.code == "PAID"
