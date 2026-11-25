"""УВ-2: отказ почты по договору, счёту, акту и приглашению возвращается отправителю строкой в колокольчик."""

from __future__ import annotations

import pytest

from accounts.models import CustomUser
from core.models import EmailLog
from notifications import mail_bus
from notifications.models import Notification


def failed(log: EmailLog, kind: str, ref_id: str) -> dict:
    return {
        "requester": "erp",
        "request_key": f"erp:email_log:{log.pk}",
        "purpose": "erp_mail",
        "ref": {"kind": kind, "id": ref_id},
        "reason": "mailbox_unavailable",
        "detail": "550 no such user",
        "attempts": 1,
    }


def queued_log(template: str, to: str) -> EmailLog:
    return EmailLog.objects.create(
        template=template, channel="transactional", subject="s", to_emails=[to], status=EmailLog.STATUS_QUEUED
    )


@pytest.fixture
def author(contract_world):
    user = CustomUser.objects.create_user(email="sender@notify.test", username="sender@notify.test", password="x")
    contract = contract_world["contracts"]["sent"]
    contract.quote.prepared_by = user
    contract.quote.save(update_fields=["prepared_by"])
    return user


@pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
def test_failed_document_mail_tells_the_sender_once(contract_world, author, kind):
    contract = contract_world["contracts"]["sent"]
    deal = contract.deal
    if kind == "contract":
        doc = contract
    else:
        doc = {"invoice": contract_world["invoices"], "act": contract_world["acts"]}[kind]
        doc = next(iter(doc.values()))
        deal = doc.deal
        deal.manager = author
        deal.save(update_fields=["manager"])
    log = queued_log("document_link_sent", "client@example.org")

    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, failed(log, kind, str(doc.pk)))
    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, failed(log, kind, str(doc.pk)))  # повтор итога

    rows = Notification.objects.filter(event_code=f"{kind}.email_failed")
    assert [(n.user_id, n.deal_id) for n in rows] == [(author.pk, deal.pk)]
    note = rows.get()
    assert "client@example.org" in note.message
    assert note.link.startswith("/eds/projects/")
    assert note.event_params["number"] == (doc.number or f"#{doc.pk}")


def test_delivered_mail_and_unknown_kind_make_no_notification(contract_world, author):
    contract = contract_world["contracts"]["sent"]
    log = queued_log("document_link_sent", "client@example.org")
    mail_bus.apply_mail_result(mail_bus.MAIL_SENT, failed(log, "contract", str(contract.pk)))
    other = queued_log("document_link_sent", "client@example.org")
    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, failed(other, "newsletter", "1"))
    assert not Notification.objects.filter(event_code__endswith=".email_failed").exists()


def test_failed_invitation_goes_to_the_one_who_invited(contract_world, author, client_contact):
    log = queued_log("portal_invitation", "invitee@example.org")

    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, failed(log, "invitation", f"{client_contact.pk}:{author.pk}"))

    (note,) = Notification.objects.filter(event_code="invitation.email_failed")
    assert note.user_id == author.pk
    assert client_contact.name in note.title


def test_failed_mail_without_a_known_sender_stays_in_the_mail_log_only(contract_world):
    contract = contract_world["contracts"]["sent"]
    contract.quote.prepared_by = None
    contract.quote.save(update_fields=["prepared_by"])
    contract.deal.manager = None
    contract.deal.assigned_to = None
    contract.deal.save(update_fields=["manager", "assigned_to"])
    log = queued_log("document_link_sent", "client@example.org")

    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, failed(log, "contract", str(contract.pk)))

    log.refresh_from_db()
    assert log.status == EmailLog.STATUS_FAILED
    assert not Notification.objects.filter(event_code="contract.email_failed").exists()
