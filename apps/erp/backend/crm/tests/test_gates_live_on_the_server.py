"""Гейты, которые до прогона 20-08 жили ТОЛЬКО в браузере.

Общий класс: кнопка отказывает, а тот же запрос тем же токеном мимо интерфейса проходит. Значит
защиты нет — есть её изображение. Оба случая найдены прогоном на локальном стенде и подтверждены
скептиком: он воспроизвёл их своей песочницей и своим замером, а `git blame` показал, что оба
живут с первых недель соответствующей подсистемы, а не появились недавно.

Ловушка, из-за которой дыра с переплатой прожила четыре месяца при зелёном наборе:
`test_billing_payment_act_paths.py::test_fully_paid_invoice_takes_no_more` НАЗЫВАЕТСЯ так, будто
проверяет запрет переплаты, а меряет только ветку «счёт уже PAID, доплатить сверху». Один платёж
больше остатка по живому счёту не покрывал ни один тест. Имя теста утверждало больше, чем тест
проверял.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.testing import make_cashier
from crm.constants import DealStageCode, InvoiceStatusCode
from crm.models import Deal, DealStage, Invoice, Quote, QuoteItem
from crm.services.billing import record_payment
from crm.services.deals import transition_deal_stage


@pytest.fixture
def buyer(db):
    company = Company.objects.create(name="Гейт-Покупатель", inn="770000101")
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    user = CustomUser.objects.create_user(email="gate.buyer@test.uz", username="gate_buyer", password="pw")
    CompanyMember.objects.create(user=user, company=company, role=owner_role, is_active=True, is_primary=True)
    return {"company": company, "user": user}


# ── Деньги: сумма не больше остатка ─────────────────────────────────────────


@pytest.mark.django_db
def test_payment_larger_than_balance_is_refused(buyer):
    """Курлом мимо браузера — та же сумма, что интерфейс отбивает тостом."""
    from crm.models import InvoiceStatus

    deal = Deal.objects.create(title="Переплата", company=buyer["company"], client=buyer["user"])
    invoice = Invoice.objects.create(
        deal=deal,
        number="GATE-INV-OVP",
        status=InvoiceStatus.objects.get(code=InvoiceStatusCode.ISSUED),
        total_incl_vat=Decimal("1000000.00"),
        amount_paid=Decimal("0.00"),
    )

    payment, error = record_payment(invoice.pk, make_cashier(), amount="999999999.00")

    assert payment is None
    assert error == "PAYMENT_EXCEEDS_BALANCE_DUE"
    invoice.refresh_from_db()
    assert invoice.amount_paid == Decimal("0.00"), "деньги записались вопреки отказу"
    assert invoice.status.code != InvoiceStatusCode.PAID


@pytest.mark.django_db
def test_payment_exactly_equal_to_balance_passes(buyer):
    """Запрет не должен задевать нормальный путь: ровно остаток — законная оплата."""
    from crm.models import InvoiceStatus

    deal = Deal.objects.create(title="Ровно остаток", company=buyer["company"], client=buyer["user"])
    invoice = Invoice.objects.create(
        deal=deal,
        number="GATE-INV-EXACT",
        status=InvoiceStatus.objects.get(code=InvoiceStatusCode.ISSUED),
        total_incl_vat=Decimal("500000.00"),
        amount_paid=Decimal("0.00"),
    )

    payment, error = record_payment(invoice.pk, make_cashier(), amount="500000.00", paid_at=timezone.localdate())

    assert error is None and payment is not None
    invoice.refresh_from_db()
    assert invoice.status.code == InvoiceStatusCode.PAID


@pytest.mark.django_db
def test_second_payment_cannot_exceed_the_remainder(buyer):
    """Частичная оплата сдвигает границу: второй платёж меряется ОСТАТКОМ, а не суммой счёта."""
    from crm.models import InvoiceStatus

    deal = Deal.objects.create(title="Частями", company=buyer["company"], client=buyer["user"])
    invoice = Invoice.objects.create(
        deal=deal,
        number="GATE-INV-PART",
        status=InvoiceStatus.objects.get(code=InvoiceStatusCode.ISSUED),
        total_incl_vat=Decimal("1000000.00"),
        amount_paid=Decimal("0.00"),
    )
    record_payment(invoice.pk, make_cashier(), amount="400000.00", paid_at=timezone.localdate(), reference="part-1")

    _payment, error = record_payment(
        invoice.pk, make_cashier(), amount="700000.00", paid_at=timezone.localdate(), reference="part-2"
    )

    assert error == "PAYMENT_EXCEEDS_BALANCE_DUE"
    invoice.refresh_from_db()
    assert invoice.amount_paid == Decimal("400000.00")


# ── Заявка: без позиций продавцу не уходит ──────────────────────────────────


@pytest.mark.django_db
def test_empty_request_cannot_be_submitted(buyer):
    """«Add at least one line item» жило только в браузере."""
    deal = Deal.objects.create(
        title="Пустая заявка",
        company=buyer["company"],
        client=buyer["user"],
        stage=DealStage.objects.get(code=DealStageCode.DRAFT),
    )

    result, error = transition_deal_stage(deal, DealStageCode.RFQ_OPEN, buyer["user"])

    assert result is None
    assert error == "REQUEST_HAS_NO_ITEMS"
    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.DRAFT


@pytest.mark.django_db
def test_request_with_items_is_submitted(buyer):
    """Запрет не должен ломать нормальный путь."""
    deal = Deal.objects.create(
        title="Заявка с позицией",
        company=buyer["company"],
        client=buyer["user"],
        stage=DealStage.objects.get(code=DealStageCode.DRAFT),
    )
    quote = Quote.objects.create(deal=deal, version=1)
    QuoteItem.objects.create(quote=quote, display_type=QuoteItem.DisplayType.ITEM, quantity=Decimal("1"))

    result, error = transition_deal_stage(deal, DealStageCode.RFQ_OPEN, buyer["user"])

    assert error is None and result is not None
    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.RFQ_OPEN


@pytest.mark.django_db
def test_force_override_still_bypasses_the_gate(buyer):
    """Force-override оператора намеренно проходит мимо гейтов — это его смысл."""
    deal = Deal.objects.create(
        title="Принудительно",
        company=buyer["company"],
        client=buyer["user"],
        stage=DealStage.objects.get(code=DealStageCode.DRAFT),
    )

    result, error = transition_deal_stage(deal, DealStageCode.RFQ_OPEN, buyer["user"], validate_fsm=False)

    assert error is None and result is not None
