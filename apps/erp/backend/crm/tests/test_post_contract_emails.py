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
from accounts.testing import make_cashier
from accounts.tests.requisites import ready_for_invoices
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
from crm.tests.delivery_support import mark_delivered


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
    )
    ready_for_invoices(company)
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
def world(lookups):
    buyer_co = _company("Buyer G3", "B100", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@g3.test")
    seller_co = _company("Seller G3", "S100", "SUPPLIER")
    seller_user = _member(seller_co, "seller@g3.test", can_sell=True)
    # Напоминания о просрочке включает компания-продавец (по умолчанию выключено — DECISIONS 2026-11-04)
    seller_settings = seller_co.settings
    seller_settings.remind_overdue_invoices = True
    seller_settings.save(update_fields=["remind_overdue_invoices"])

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


def _letters(mock) -> list:
    """ДК-3: письма с документом по ссылке получателя — `(вид документа, адрес)` из постановки в очередь."""
    return [(call.args[0], call.args[2]) for call in mock.delay.call_args_list]


def _deal_contact(world, email="client@buyer-g3.example"):
    """Контакт сделки: ему идут письма о счёте, акте и напоминании (ДК-3), а не участникам компании в ERP."""
    from parties.models import Contact

    contact = Contact.objects.create(company=world["buyer_co"], name="Deal Contact", email=email, can_act=True)
    world["deal"].contact = contact
    world["deal"].save(update_fields=["contact"])
    return contact


# ── 1. Счёт выставлен → письмо покупателю ────────────────────────────────────


def test_issuing_an_invoice_emails_the_deal_contact_not_the_company_members(world, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice

    contact = _deal_contact(world)
    invoice = _invoice(world, "DRAFT")
    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("notifications.tasks.send_transactional_email") as mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            issued, error = issue_invoice(invoice, world["seller_user"])

    assert error is None, error
    assert _letters(letter) == [("invoice", contact.email)], "письмо со ссылкой — контакту сделки"
    assert _sent(mail) == [], "прежним участникам компании в ERP письмо о счёте не уходит"
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
                invoice.id, make_cashier(), amount=Decimal("112"), paid_at=timezone.localdate()
            )

    assert error is None, error
    assert payment is not None
    sent = _sent(mail)
    assert [template for template, _ in sent] == ["payment_received"]
    assert sent[0][1] == [world["seller_user"].email], "квитанция ушла не продавцу"


# ── 3. Акт выставлен → письмо заказчику ──────────────────────────────────────


def test_issuing_an_act_emails_the_deal_contact(world, django_capture_on_commit_callbacks):
    from crm.services.billing import generate_act

    contact = _deal_contact(world)
    invoice = _invoice(world, "PAID", paid=Decimal("112"))
    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("notifications.tasks.send_transactional_email") as mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            mark_delivered(invoice.deal)
            act, error = generate_act(invoice.id, actor=world["seller_user"])

    assert error is None, error
    assert act is not None
    assert _letters(letter) == [("act", contact.email)]
    assert _sent(mail) == []


# ── 4. Напоминание о просрочке ───────────────────────────────────────────────


def test_overdue_invoice_gets_one_reminder(world, django_capture_on_commit_callbacks):
    from crm.tasks import send_payment_reminders

    contact = _deal_contact(world)
    invoice = _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=10))

    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("notifications.tasks.send_transactional_email") as mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            result = send_payment_reminders()

    assert result["reminded"] == 1
    assert [
        (kind, email, call.args[4]) for (kind, email), call in zip(_letters(letter), letter.delay.call_args_list)
    ] == [("invoice", contact.email, True)], "напоминание — письмо о счёте с признаком напоминания"
    assert _sent(mail) == []
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


# ── 7. Контактам компании-клиента (NOTIFY-2, ADR-0023 п. 2) ─────────────────────────────────────────────────
#
# Прежде письма о счёте, акте и просрочке адресовались только `buyer_team_user_ids` — пользователям ERP компании-покупателя.
# У клиентов кабинета пользователей ERP нет (FIX-13), поэтому контакты клиента этих писем не получали никогда. Теперь
# маршрутизатор уведомлений шлёт письмо `portal_notice` каждому действующему контакту без Telegram (с Telegram — пишет бот
# CRM), а пользователям покупателя — как прежде.


@pytest.fixture
def contacts(world):
    from django.utils import timezone as tz
    from parties.models import Contact

    # Приглашённые в кабинет: письмо-уведомление получают контакт документа и приглашённые (решение лида по #402)
    plain = Contact.objects.create(
        company=world["buyer_co"],
        name="Plain Contact",
        email="plain@buyer-g3.example",
        can_act=True,
        language="en",
        invited_at=tz.now(),
    )
    telegram = Contact.objects.create(
        company=world["buyer_co"],
        name="Telegram Contact",
        email="tg@buyer-g3.example",
        telegram_user_id=4242,
        can_act=True,
        invited_at=tz.now(),
    )
    world["deal"].contact = plain  # контакт сделки: получатель писем с документами
    world["deal"].save(update_fields=["contact"])
    # Не приглашён и не контакт документа: только колокольчик, первым письмом ему придёт приглашение
    Contact.objects.create(company=world["buyer_co"], name="Stranger", email="stranger@buyer-g3.example")
    # Компания сопоставлена клиенту CRM: события доходят до бота, контакт с Telegram получает сообщение бота
    from integration.models import CrmClientMapping

    CrmClientMapping.objects.create(crm_client_id=99001, company=world["buyer_co"])
    return {"plain": plain, "telegram": telegram}


def _contact_mail(mock) -> list:
    """Адресаты писем уведомлений кабинета, поставленных в очередь (id строки ленты → адрес контакта)."""
    from portal.models import PortalNotice

    ids = [call.args[0] for call in mock.delay.call_args_list]
    return sorted(PortalNotice.objects.get(pk=pk).contact.email for pk in ids)


def test_issuing_an_invoice_emails_contacts_without_telegram(world, contacts, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice

    invoice = _invoice(world, "DRAFT")
    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("portal.tasks.send_notice_email") as contact_mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            issue_invoice(invoice, world["seller_user"])

    assert _letters(letter) == [("invoice", "plain@buyer-g3.example")], "контакту сделки — письмо с документом"
    assert _contact_mail(contact_mail) == [], "ему же второе письмо-уведомление не нужно, контакту с Telegram пишет бот"


def test_issuing_an_act_emails_contacts_without_telegram(world, contacts, django_capture_on_commit_callbacks):
    from crm.services.billing import generate_act

    invoice = _invoice(world, "PAID", paid=Decimal("112"))
    with patch("crm.tasks.send_document_link_email") as letter, patch("portal.tasks.send_notice_email") as contact_mail:
        with django_capture_on_commit_callbacks(execute=True):
            mark_delivered(invoice.deal)
            act, error = generate_act(invoice.id, actor=world["seller_user"])

    assert error is None, error
    assert _letters(letter) == [("act", "plain@buyer-g3.example")]
    assert _contact_mail(contact_mail) == []


def test_payment_reminder_reaches_every_contact(world, contacts, django_capture_on_commit_callbacks):
    """Бот о просрочке не пишет — письмо получает и контакт с Telegram (уведомление не теряется)."""
    from crm.tasks import send_payment_reminders

    _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=10))
    with patch("crm.tasks.send_document_link_email") as letter, patch("portal.tasks.send_notice_email") as contact_mail:
        with django_capture_on_commit_callbacks(execute=True):
            send_payment_reminders()

    assert _letters(letter) == [("invoice", "plain@buyer-g3.example")]
    assert _contact_mail(contact_mail) == [
        "tg@buyer-g3.example"
    ], "контакт с Telegram: бот о просрочке не пишет, письмо идёт"


def test_contact_with_the_deal_contact_address_gets_one_invoice_email(
    world, contacts, django_capture_on_commit_callbacks
):
    """Контакту сделки письмо о счёте шлёт `document_letters`; другой контакт с тем же адресом второго не получает."""
    from parties.models import Contact
    from portal.models import NoticeChannel, PortalNotice

    from crm.services.invoice_lifecycle import issue_invoice

    same = Contact.objects.create(
        company=world["buyer_co"],
        name="Same Person",
        email="PLAIN@buyer-g3.example",
        invited_at=timezone.now(),
    )
    invoice = _invoice(world, "DRAFT")
    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("portal.tasks.send_notice_email") as contact_mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            issue_invoice(invoice, world["seller_user"])

    assert _letters(letter) == [("invoice", "plain@buyer-g3.example")]
    assert PortalNotice.objects.get(contact=same, kind="invoice_issued").channel == NoticeChannel.SOURCE
    assert same.email not in _contact_mail(contact_mail)


def test_reminders_are_off_by_default(world, contacts, django_capture_on_commit_callbacks):
    """Выключено в настройках продавца — ни письма пользователям, ни уведомления контактам, счёт не отмечен (Stripe,
    QuickBooks: напоминания включает продавец)."""
    from portal.models import PortalNotice

    from crm.tasks import send_payment_reminders

    settings_row = world["seller_co"].settings
    settings_row.remind_overdue_invoices = False
    settings_row.save(update_fields=["remind_overdue_invoices"])
    invoice = _invoice(world, "ISSUED", due_date=timezone.localdate() - timedelta(days=10))
    with (
        patch("crm.tasks.send_document_link_email") as letter,
        patch("portal.tasks.send_notice_email") as contact_mail,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            assert send_payment_reminders()["reminded"] == 0

    assert _letters(letter) == [] and _contact_mail(contact_mail) == []
    assert not PortalNotice.objects.filter(kind="payment_overdue").exists()
    invoice.refresh_from_db()
    assert invoice.payment_reminder_sent_at is None, "после включения напоминание уйдёт"


def test_reminders_schedule_is_daily_at_ten_tashkent(db):
    from django_celery_beat.models import PeriodicTask

    task = PeriodicTask.objects.get(task="crm.send_payment_reminders")
    assert task.enabled
    assert (task.crontab.hour, task.crontab.minute, str(task.crontab.timezone)) == ("10", "0", "Asia/Tashkent")


def test_reminder_switch_in_company_settings(world):
    from accounts.services.company_settings import update_company_settings

    owner = CustomUser.objects.create_superuser(email="root@g3.test", username="root@g3.test", password="x")
    row, error = update_company_settings(owner, world["seller_co"], {"remind_overdue_invoices": False})
    assert error is None and row.remind_overdue_invoices is False
    _row, error = update_company_settings(owner, world["seller_co"], {"remind_overdue_invoices": "yes"})
    assert error == "BAD_BOOLEAN"
