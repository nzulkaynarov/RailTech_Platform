# flake8: noqa: F811  (fixtures `world`/`lookups` are imported from test_post_contract_emails)
"""СЦ-7: e-mails and bell messages of the deal path read like screens — money with separators and currency,
dates ДД.ММ.ГГГГ, deal numbers instead of database ids."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from accounts.testing import make_cashier
from crm.tests.delivery_support import mark_delivered
from crm.tests.test_post_contract_emails import _invoice as _raw_invoice
from crm.tests.test_post_contract_emails import lookups, world  # noqa: F401,F811  (fixtures)
from notifications.emails import _render_bodies
from notifications.models import Notification
from notifications.tests.human_text import assert_human_text

NBSP = " "


_seq = iter(range(1, 1000))


def _invoice(world, code="DRAFT", **kwargs):
    """The shared helper numbers invoices with a timestamp; a human number keeps the text checks honest."""
    invoice = _raw_invoice(world, code, **kwargs)
    invoice.number = f"INV-{next(_seq):03d}"
    invoice.save()
    return invoice


def _captured(mock):
    """(template, context) of every queued mail."""
    return [(call.args[0], call.args[1]) for call in mock.delay.call_args_list]


def _render_all(template, context):
    subject, text, html = _render_bodies(template, context)
    for part in (subject, text, html):
        assert_human_text(part)
    return text, html


def test_invoice_issued_and_reminder_mails_show_money_and_dates_like_screens(world, django_capture_on_commit_callbacks):
    from crm.services.invoice_lifecycle import issue_invoice
    from crm.tasks import send_payment_reminders

    invoice = _invoice(world, "DRAFT")
    invoice.total_incl_vat = Decimal("1500000")
    invoice.due_date = timezone.localdate() - timedelta(days=10)
    invoice.save()
    due = invoice.due_date.strftime("%d.%m.%Y")

    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            issue_invoice(invoice, world["seller_user"])
        invoice.refresh_from_db()
        invoice.due_date = timezone.localdate() - timedelta(days=10)
        invoice.save()
        with django_capture_on_commit_callbacks(execute=True):
            send_payment_reminders()
    sent = dict(_captured(mail))
    assert set(sent) == {"invoice_issued", "payment_reminder"}

    for template, context in sent.items():
        text, html = _render_all(template, context)
        assert f"1{NBSP}500{NBSP}000,00{NBSP}UZS" in text and f"1{NBSP}500{NBSP}000,00{NBSP}UZS" in html
    assert due in _render_all("payment_reminder", sent["payment_reminder"])[0]


def test_payment_and_act_mails_show_money_like_screens(world, django_capture_on_commit_callbacks):
    from crm.services.billing import generate_act, record_payment

    invoice = _invoice(world, "ISSUED")
    invoice.total_incl_vat = Decimal("2500000")
    invoice.save()
    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            record_payment(invoice.id, make_cashier(), amount=Decimal("1000000"), paid_at=timezone.localdate())
    template, context = _captured(mail)[0]
    assert template == "payment_received"
    text, _html = _render_all(template, context)
    assert f"1{NBSP}000{NBSP}000,00{NBSP}UZS" in text and f"2{NBSP}500{NBSP}000,00{NBSP}UZS" in text

    paid = _invoice(world, "PAID", paid=Decimal("112"))
    with patch("notifications.tasks.send_transactional_email") as mail:
        with django_capture_on_commit_callbacks(execute=True):
            mark_delivered(paid.deal)
            act, error = generate_act(paid.id, actor=world["seller_user"])
    assert error is None, error
    ((template, context),) = _captured(mail)
    assert template == "act_awaiting_acceptance"
    text, _html = _render_all(template, context)
    assert f"{NBSP}UZS" in text


def test_bell_messages_of_the_act_and_payment_path_name_the_deal_by_number(world, django_capture_on_commit_callbacks):
    from crm.services import deal_notifications as dn
    from crm.services.billing import generate_act, record_payment
    from crm.services.invoice_lifecycle import issue_invoice

    deal = world["deal"]
    assert deal.number
    invoice = _invoice(world, "DRAFT")
    invoice.total_incl_vat = Decimal("2500000")
    invoice.save()
    with patch("notifications.tasks.send_transactional_email"):
        with django_capture_on_commit_callbacks(execute=True):
            issue_invoice(invoice, world["seller_user"])
            record_payment(invoice.id, make_cashier(), amount=Decimal("1000000"), paid_at=timezone.localdate())
        paid = _invoice(world, "PAID", paid=Decimal("112"))
        with django_capture_on_commit_callbacks(execute=True):
            mark_delivered(paid.deal)
            act, _error = generate_act(paid.id, actor=world["seller_user"])
    dn.notify_act_signed(act, world["seller_user"], accepted_by_client=True)
    dn.notify_act_signed(act, world["seller_user"])
    dn.notify_act_rejected(act, world["buyer_user"], "Неверная сумма")
    dn.notify_act_cancelled(act, world["seller_user"], "Ошибка")

    messages = list(Notification.objects.values_list("message", flat=True))
    assert len(messages) >= 6
    for message in messages:
        assert_human_text(message)
    assert any(deal.number in message for message in messages)
    assert any(f"1{NBSP}000{NBSP}000,00{NBSP}UZS" in message for message in messages), messages


def test_delivery_status_and_overdue_bell_texts_are_human(world):
    from crm.models import Fulfillment
    from crm.services import deal_notifications as dn

    deal = world["deal"]
    fulfillment = Fulfillment.objects.create(deal=deal, expected_delivery_date=timezone.localdate())
    dn.notify_fulfillment_status(fulfillment, "SHIPPED", None)
    dn.notify_delivery_overdue(fulfillment)
    messages = list(Notification.objects.values_list("message", flat=True))
    assert messages
    for message in messages:
        assert_human_text(message)
    assert any(timezone.localdate().strftime("%d.%m.%Y") in message for message in messages)


def test_calc_journal_has_no_plural_stub():
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[2] / "crm/services/calculation.py").read_text()
    assert "строк(и)" not in source and "pluralize_ru(len(created)" in source


def test_no_deal_id_hash_left_in_bell_messages():
    """The bell and journals show deal numbers; `message=f"…#{…}"` is how database ids leaked (СЦ-7 rows)."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    files = [
        "crm/services/assignment.py",
        "crm/services/calc_tasks.py",
        "crm/services/contracts.py",
        "crm/services/deal_notifications.py",
        "crm/services/generated_documents.py",
        "crm/services/invoice_lifecycle.py",
        "crm/tasks.py",
        "notifications/signals.py",
        "sales/services/delivery_lines.py",
    ]
    leaks = [
        f"{name}: {line.strip()}"
        for name in files
        for line in (root / name).read_text().splitlines()
        if re.search(r'message=f?".*#\{', line) or re.search(r"\(\"[^\"]*\", f\"[^\"]*#\{", line)
    ]
    assert leaks == []
