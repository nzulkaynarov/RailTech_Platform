"""G1 — акт выпускается по факту поставки, срок оплаты считается от выставления.

Источник решений: `Docs/old/specs/spec-post-contract-open-questions-2026-07-30.md` §1 и §5.

Два изменения поведения:

1. **Акт больше не выпускается в момент выигрыша сделки.** Прежний вызов в
   `auto_invoice_on_closed_won` был мёртвым по построению (счёт рождается DRAFT, а `generate_act`
   требует ISSUED/PARTIAL/PAID), и бенчмарк подтвердил, что чинить его не следовало: ни один
   эталон не связывает закрывающий документ с подписанием сделки. Подсказка «сформировать акт»
   переехала на ФАКТ ПОСТАВКИ — как в Odoo (валидация отгрузки) и SAP (приёмка получателем).

2. **Срок оплаты отсчитывается от даты выставления**, а не от создания черновика: черновик мог
   пролежать неделю, и покупатель получал счёт с уже наполовину истёкшим сроком. Явно заданная
   продавцом дата не пересчитывается.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.constants import DEFAULT_INVOICE_DUE_DAYS
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)


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

    for code in ("INFO", "SUCCESS", "WARNING"):
        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name,
        inn=inn,
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
    )
    return user


@pytest.fixture
def won_deal(lookups):
    """Выигранная сделка с подписанным договором — вход в auto_invoice_on_closed_won."""
    buyer_co = _company("Buyer G1", "B300", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@g1.test")
    seller_co = _company("Seller G1", "S300", "SUPPLIER")
    seller_user = _member(seller_co, "seller@g1.test", can_sell=True)

    deal = Deal.objects.create(title="G1 deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    QuoteItem.objects.create(quote=quote, imported_raw_name="Рельс", quantity=1, frozen_base_price=Decimal("100"))
    signed_at = timezone.now()
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-G1-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
        # Обе отметки обязательны: `is_fully_signed` требует и клиентскую, и менеджерскую,
        # иначе цепочка честно застревает на «подписать договор».
        client_signer=buyer_user,
        client_signed_at=signed_at,
        manager_signer=seller_user,
        manager_signed_at=signed_at,
    )
    return {
        "deal": deal,
        "contract": contract,
        "quote": quote,
        "buyer_user": buyer_user,
        "seller_user": seller_user,
    }


# ── 1. Акт не выпускается при выигрыше сделки ────────────────────────────────


def test_winning_a_deal_creates_an_invoice_but_no_act(won_deal):
    """Автоматика на выигрыше создаёт счёт и отгрузку, но НЕ закрывающий документ."""
    from crm.tasks import auto_invoice_on_closed_won

    result = auto_invoice_on_closed_won(won_deal["deal"].id)

    assert result["invoice"] is not None, "счёт по-прежнему создаётся автоматически"
    assert result["act"] is None, "акт не должен выпускаться в момент выигрыша сделки"
    assert Act.objects.filter(deal=won_deal["deal"]).count() == 0
    assert Fulfillment.objects.filter(deal=won_deal["deal"]).exists(), "отгрузка по-прежнему заводится"


def test_auto_invoice_is_still_idempotent_and_reports_an_existing_act(won_deal):
    """Идемпотентность не пострадала: повторный прогон не плодит счета и показывает уже
    выпущенный вручную акт."""
    from crm.tasks import auto_invoice_on_closed_won

    first = auto_invoice_on_closed_won(won_deal["deal"].id)
    invoice = Invoice.objects.get(pk=first["invoice"])
    act = Act.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        invoice=invoice,
        number="ACT-G1-MANUAL",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )

    second = auto_invoice_on_closed_won(won_deal["deal"].id)

    assert second["invoice"] == invoice.id
    assert second["idempotent_reuse"] is True
    assert second["act"] == act.id, "уже существующий акт должен отражаться в отчёте задачи"
    assert Invoice.objects.filter(deal=won_deal["deal"]).count() == 1


# ── 2. Подсказка «сформировать акт» — по факту поставки ──────────────────────


def _hub(deal, user):
    from crm.services.deal_documents import deal_document_hub

    return deal_document_hub(deal, user, None)


def _issued_invoice(won_deal, code="PAID"):
    return Invoice.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        number=f"INV-G1-{code}",
        status=InvoiceStatus.objects.get(code=code),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112") if code == "PAID" else Decimal("0"),
        issued_at=timezone.localdate(),
    )


def test_paid_invoice_alone_does_not_ask_for_an_act(won_deal):
    """Ключевое изменение: оплата больше НЕ является триггером закрывающего документа."""
    _issued_invoice(won_deal, "PAID")
    Fulfillment.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        status=FulfillmentStatus.objects.get(code="PENDING"),
    )

    step = _hub(won_deal["deal"], won_deal["seller_user"])["next_step"]

    assert step["code"] != "GENERATE_ACT", "акт предложен по оплате, хотя поставки ещё не было"
    assert step["code"] == "SHIP", "после оплаты цепочка должна вести к отгрузке"


def test_delivery_asks_the_seller_for_an_act(won_deal):
    """Груз доставлен — вот теперь пора выпускать акт."""
    _issued_invoice(won_deal, "PAID")
    Fulfillment.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        status=FulfillmentStatus.objects.get(code="ACCEPTED"),
        accepted_at=timezone.now(),
    )

    step = _hub(won_deal["deal"], won_deal["seller_user"])["next_step"]

    assert step["code"] == "GENERATE_ACT"
    assert step["for_viewer"] is True, "выпускает акт продавец"
    # Подсказка ведёт В ПАНЕЛЬ счёта (`#invoices?open=<id>`), а не в пустой реестр: кнопка
    # «Generate act» живёт в панели, без object_id продавец искал её сам (глазами 17-08).
    assert step["page"] == "invoices"
    assert step["object_id"] is not None, "подсказка про акт без счёта — тупик в реестре"


def test_delivered_but_unpaid_still_asks_for_payment_first(won_deal):
    """Счёт впереди отгрузки: у нас он рождается из договора, а предоплата — обычное условие."""
    _issued_invoice(won_deal, "ISSUED")
    Fulfillment.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        status=FulfillmentStatus.objects.get(code="DELIVERED"),
    )

    step = _hub(won_deal["deal"], won_deal["buyer_user"])["next_step"]

    assert step["code"] == "PAY_INVOICE"


def _act_and_pending_shipment(won_deal, invoice_status="PAID"):
    """Заготовка тупика: счёт ОПЛАЧЕН, отгрузки нет, акт уже выпущен кнопкой.

    Именно при оплаченном счёте отгрузка остаётся единственным незакрытым делом — и именно
    здесь прежняя подсказка навсегда замирала на «подпишите акт». При неоплаченном счёте
    цепочка честно зовёт платить (счёт идёт раньше отгрузки: предоплата — обычное условие
    поставки на этом рынке), и тупика нет.
    """
    invoice = _issued_invoice(won_deal, invoice_status)
    Act.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        invoice=invoice,
        number="ACT-G1-PENDING",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    Fulfillment.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        status=FulfillmentStatus.objects.get(code="PENDING"),
    )


def test_issued_act_outranks_everything_else_for_the_side_that_must_answer(won_deal):
    """Выставленный акт висит на второй стороне — он приоритетнее любого следующего действия.

    Правило осталось прежним; уточнилось, КОМУ оно адресовано (см. соседний тест).
    """
    _act_and_pending_shipment(won_deal)

    step = _hub(won_deal["deal"], won_deal["buyer_user"])["next_step"]

    assert step["code"] == "SIGN_ACT"


def test_the_seller_is_still_told_to_ship_while_the_shipment_is_open(won_deal):
    """Акт можно выпустить кнопкой при нулевой отгрузке — и подсказка переставала звать
    отгружать: шаг висел первым в цепочке и возвращался ОБЕИМ сторонам. Продавец получал
    «подпишите акт» и больше ни одного упоминания поставки, хотя она осталась единственным
    незакрытым делом (замер 26-08, находка 13).

    Ничего не запрещено: акт остаётся выпущенным, кнопка подписи на месте. Изменилась только
    ПОДСКАЗКА — она называет продавцу то дело, которое за ним.
    """
    _act_and_pending_shipment(won_deal)

    step = _hub(won_deal["deal"], won_deal["seller_user"])["next_step"]

    assert step["code"] == "SHIP"


def test_a_delivered_shipment_returns_the_act_to_the_top_for_the_seller(won_deal):
    """Обратная сторона: когда за продавцом дел не осталось, акт снова важнее всего."""
    _issued_invoice(won_deal, "ISSUED")
    Act.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        invoice=Invoice.objects.filter(deal=won_deal["deal"]).first(),
        number="ACT-G1-DONE",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    Fulfillment.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        status=FulfillmentStatus.objects.get(code="DELIVERED"),
    )

    step = _hub(won_deal["deal"], won_deal["seller_user"])["next_step"]

    assert step["code"] == "SIGN_ACT"


# ── 3. Срок оплаты — от даты выставления ─────────────────────────────────────


def test_due_date_is_counted_from_issue_not_from_draft_creation(won_deal):
    """Черновик пролежал 10 дней — покупатель всё равно получает полный срок оплаты."""
    from crm.services.invoice_lifecycle import issue_invoice

    invoice = Invoice.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        number="INV-G1-STALE",
        status=InvoiceStatus.objects.get(code="DRAFT"),
        total_incl_vat=Decimal("112"),
        due_date=timezone.localdate() - timedelta(days=10) + timedelta(days=DEFAULT_INVOICE_DUE_DAYS),
    )
    stale_due_date = invoice.due_date

    issued, error = issue_invoice(invoice, won_deal["seller_user"])

    assert error is None, error
    assert issued.due_date == issued.issued_at + timedelta(days=DEFAULT_INVOICE_DUE_DAYS)
    assert issued.due_date > stale_due_date, "срок оплаты должен был сдвинуться вперёд"


def test_a_manually_set_due_date_survives_issuing(won_deal):
    """Особые условия договора важнее умолчания — руками заданную дату не пересчитываем."""
    from crm.services.invoice_lifecycle import issue_invoice, update_invoice_draft

    invoice = Invoice.objects.create(
        deal=won_deal["deal"],
        contract=won_deal["contract"],
        number="INV-G1-MANUAL",
        status=InvoiceStatus.objects.get(code="DRAFT"),
        total_incl_vat=Decimal("112"),
    )
    agreed = timezone.localdate() + timedelta(days=45)
    updated, error = update_invoice_draft(invoice, won_deal["seller_user"], due_date=agreed)
    assert error is None, error
    assert updated.due_date_is_manual is True

    issued, error = issue_invoice(updated, won_deal["seller_user"])

    assert error is None, error
    assert issued.due_date == agreed, "ручной срок оплаты затёрт пересчётом"
