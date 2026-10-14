"""Четыре письма пути «после контракта» (G3).

Решение и его основания — `Docs/old/specs/spec-post-contract-open-questions-2026-07-30.md` §3.

До этой волны на отрезке счёт → оплата → закрывающий документ не было ни одного письма, только
уведомления внутри приложения. Покупатель здесь часто внешний контрагент, который в систему
может и не зайти, — а оплата это действие ВНЕ системы.

Писем ровно четыре, и это тот минимум, на котором сходятся эталоны. Проверяется и обратное:
события, которым письмо НЕ полагается (создание черновика, отмена счёта), его не порождают —
репутация домена считается целиком, и лишние письма бьют по доставке нужных.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.constants import DEFAULT_INVOICE_DUE_DAYS
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Invoice,
    InvoiceItem,
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
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 80})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 50})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 40})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    from crm.models import ActStatus

    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
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
def world(lookups):
    buyer_co = _company("Buyer G3", "B100", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@g3.test", can_buy=True)
    seller_co = _company("Seller G3", "S100", "SUPPLIER")
    seller_user = _member(seller_co, "seller@g3.test", can_sell=True)

    deal = Deal.objects.create(title="G3 deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    quote_item = QuoteItem.objects.create(
        quote=quote, imported_raw_name="Рельс", quantity=1, frozen_base_price=Decimal("100")
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-G3-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "deal": deal,
        "contract": contract,
        "quote_item": quote_item,
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "seller_co": seller_co,
        "seller_user": seller_user,
    }


def _invoice(world, code="DRAFT", *, paid=Decimal("0"), due_date=None):
    invoice = Invoice.objects.create(
        deal=world["deal"],
        contract=world["contract"],
        number=f"INV-G3-{code}-{timezone.now().timestamp()}",
        status=InvoiceStatus.objects.get(code=code),
        total_incl_vat=Decimal("112"),
        amount_paid=paid,
        due_date=due_date,
    )
    InvoiceItem.objects.create(
        invoice=invoice,
        description="Рельс",
        quantity=1,
        unit_price_excl_vat=Decimal("100"),
        line_total_excl_vat=Decimal("100"),
        source_quote_item=world["quote_item"],
    )
    return invoice


def _sent(mock) -> list:
    """Список (шаблон, адресаты) из вызовов постановки письма в очередь."""
    return [(call.args[0], call.kwargs.get("to")) for call in mock.delay.call_args_list]


# ── 1. Счёт выставлен → письмо покупателю ────────────────────────────────────


def test_issuing_an_invoice_emails_the_buyer(world, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice

    invoice = _invoice(world, "DRAFT")
    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            issued, error = issue_invoice(invoice, world["seller_user"])

    assert error is None, error
    sent = _sent(mail)
    assert [template for template, _ in sent] == ["invoice_issued"]
    assert sent[0][1] == [world["buyer_user"].email], "письмо ушло не покупателю"
    assert issued.status_code == "ISSUED"


def test_creating_a_draft_sends_no_email(world, django_capture_on_commit_callbacks):
    """Черновик письма НЕ порождает — у эталонов письмо привязано к выставлению."""
    from crm.services.billing import generate_invoice_from_contract

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            generate_invoice_from_contract(world["contract"].id)

    assert _sent(mail) == []


# ── 2. Оплата получена → письмо продавцу ─────────────────────────────────────


def test_recording_a_payment_emails_the_seller(world, django_capture_on_commit_callbacks):
    from crm.services.billing import record_payment

    invoice = _invoice(world, "ISSUED")
    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            payment, error = record_payment(
                invoice.id, world["buyer_user"], amount=Decimal("112"), paid_at=timezone.localdate()
            )

    assert error is None, error
    assert payment is not None
    sent = _sent(mail)
    assert [template for template, _ in sent] == ["payment_received"]
    assert sent[0][1] == [world["seller_user"].email], "квитанция ушла не продавцу"


# ── 3. Акт выставлен → письмо заказчику ──────────────────────────────────────


def test_issuing_an_act_emails_the_buyer(world, django_capture_on_commit_callbacks):
    from crm.services.billing import generate_act

    invoice = _invoice(world, "PAID", paid=Decimal("112"))
    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            act, error = generate_act(invoice.id, actor=world["seller_user"])

    assert error is None, error
    assert act is not None
    sent = _sent(mail)
    assert [template for template, _ in sent] == ["act_awaiting_acceptance"]
    assert sent[0][1] == [world["buyer_user"].email]


# ── 4. Напоминание о просрочке ───────────────────────────────────────────────


def test_overdue_invoice_gets_one_reminder(world, django_capture_on_commit_callbacks):
    from crm.tasks import send_payment_reminders

    invoice = _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=10))

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            result = send_payment_reminders()

    assert result["reminded"] == 1
    sent = _sent(mail)
    assert [template for template, _ in sent] == ["payment_reminder"]
    assert sent[0][1] == [world["buyer_user"].email]
    invoice.refresh_from_db()
    assert invoice.payment_reminder_sent_at is not None


def test_the_reminder_is_not_repeated_daily(world, django_capture_on_commit_callbacks):
    """Хранится ровно факт отправки — иначе ежедневная задача слала бы письмо каждый день."""
    from crm.tasks import send_payment_reminders

    _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=10))
    with django_capture_on_commit_callbacks(execute=True):
        send_payment_reminders()

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            second = send_payment_reminders()

    assert second["reminded"] == 0
    assert _sent(mail) == []


def test_an_invoice_within_its_grace_period_is_not_reminded(world, django_capture_on_commit_callbacks):
    """Напоминание уходит не в день срока, а после льготных дней."""
    from crm.tasks import send_payment_reminders

    _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=1))

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            result = send_payment_reminders()

    assert result["reminded"] == 0
    assert _sent(mail) == []


def test_a_paid_invoice_is_never_reminded(world, django_capture_on_commit_callbacks):
    from crm.tasks import send_payment_reminders

    _invoice(world, "PAID", paid=Decimal("112"), due_date=timezone.localdate() - timedelta(days=30))

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            result = send_payment_reminders()

    assert result["reminded"] == 0
    assert _sent(mail) == []


# ── 5. Срок оплаты берётся из настроек компании ──────────────────────────────


def test_due_date_uses_the_company_payment_terms(world, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice

    settings_row = world["seller_co"].settings
    settings_row.payment_terms_days = 45
    settings_row.save(update_fields=["payment_terms_days"])

    invoice = _invoice(world, "DRAFT")
    with patch("notifications.tasks.send_transactional_email"):
        with django_capture_on_commit_callbacks(execute=True):
            issued, error = issue_invoice(invoice, world["seller_user"])

    assert error is None, error
    assert issued.due_date == issued.issued_at + timedelta(days=45)


def test_without_a_company_setting_the_platform_default_applies(world, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice

    invoice = _invoice(world, "DRAFT")
    with patch("notifications.tasks.send_transactional_email"):
        with django_capture_on_commit_callbacks(execute=True):
            issued, _ = issue_invoice(invoice, world["seller_user"])

    assert issued.due_date == issued.issued_at + timedelta(days=DEFAULT_INVOICE_DUE_DAYS)


# ── 6. Письмо не переживает откат ────────────────────────────────────────────


def test_no_email_escapes_a_rolled_back_transaction(world):
    """Колбэки on_commit без execute=True не выполняются — наблюдаемое поведение отката."""
    from crm.services.invoice_lifecycle import issue_invoice

    invoice = _invoice(world, "DRAFT")
    with patch("notifications.tasks.send_transactional_email") as mail:
        issue_invoice(invoice, world["seller_user"])

    assert _sent(mail) == []
