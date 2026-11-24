"""ДК-4: код и личная ссылка документа приходят и в бот, если у получателя привязан Telegram.

Проверяются факты, от которых зависит безопасность и сценарий: код уходит в Telegram только того контакта, на чью ссылку он
выпущен, и только если Telegram привязан и контакт сопоставлен с CRM; код и его правила (10 минут, 45 секунд до повтора,
привязка к ссылке) те же, что у письма; в сообщении с кодом нет данных документа; ссылка в боте — та самая личная ссылка
получателя; код и токен ссылки лежат в outbox только маской.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest
from django.core import mail
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.tests import bus_support
from parties.models import Contact
from portal.models import DocumentLink, MagicLinkToken
from portal.services import doc_links
from portal.tests.test_doc_links import _env, post, sent_code  # noqa: F401 — автоиспользуемая среда и помощники ДК-2
from portal.tests.test_doc_links_kinds import (  # noqa: F401 — фикстуры документов
    act,
    contract,
    deal,
    invoice,
    mint,
    quote,
)
from rest_framework import status

# flake8: noqa: F811 — фикстуры документов импортированы из test_doc_links_kinds
pytestmark = pytest.mark.django_db

CRM_CLIENT_ID = 4242
CRM_CONTACT_ID = 57
EVENT = "document_link.telegram_requested"


@pytest.fixture(autouse=True)
def _clean_outbox():
    bus_support.reset()


@pytest.fixture
def mapped(client_company, client_contact):
    CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)
    CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=CRM_CONTACT_ID)
    return client_contact


def events_of(short=EVENT):
    return bus_support.published(short)


def request_code(raw):
    return post("code", {"token": raw})


# ── Код ───────────────────────────────────────────────────────────────────────────────────────────────────────────


class TestCode:
    def test_the_same_code_goes_to_the_linked_telegram_of_the_recipient(self, invoice, mapped):
        _, raw = mint("invoice", invoice)
        response = request_code(raw)
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json()["channels"] == ["email", "telegram"]

        (envelope,) = events_of()
        bus_support.assert_matches_contract(envelope, secret_masked=True)
        assert envelope["data"]["payload"]["code"] == "***", "код в outbox — только маской"
        data = bus_support.real_data(envelope)
        assert data["payload"]["code"] == sent_code(), "в бот уходит тот же код, что и в письмо"
        assert data["payload"]["kind"] == "code" and data["payload"]["document_kind"] == "invoice"
        assert data["payload"]["erp_contact_id"] == mapped.pk and data["payload"]["crm_contact_id"] == CRM_CONTACT_ID
        assert data["crm_client_id"] == CRM_CLIENT_ID

    def test_the_code_expires_when_the_mailed_code_expires(self, invoice, mapped):
        _, raw = mint("invoice", invoice)
        request_code(raw)
        row = MagicLinkToken.objects.get(document_link__kind="invoice")
        expires = bus_support.real_data(events_of()[0])["payload"]["expires_at"]
        assert abs(datetime.datetime.fromisoformat(expires) - row.expires_at) < datetime.timedelta(seconds=2)

    def test_without_a_linked_telegram_the_code_goes_by_mail_only(self, invoice, client_contact, client_company):
        CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)
        CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=CRM_CONTACT_ID)
        Contact.objects.filter(pk=client_contact.pk).update(telegram_user_id=None)
        _, raw = mint("invoice", invoice)
        response = request_code(raw)
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["channels"] == ["email"] and not events_of()
        assert len(mail.outbox) == 1 and re.search(r"\d{6}", mail.outbox[-1].body)

    def test_a_contact_not_matched_with_crm_gets_mail_only(self, invoice, client_contact, client_company):
        CrmClientMapping.objects.create(
            company=client_company, crm_client_id=CRM_CLIENT_ID
        )  # контакт CRM не сопоставлен
        _, raw = mint("invoice", invoice)
        assert request_code(raw).json()["channels"] == ["email"] and not events_of()

    def test_the_code_goes_only_to_the_telegram_of_the_link_recipient(self, invoice, mapped, client_company):
        # второй контакт компании — тоже с Telegram, но ссылка выпущена на первого: бот пишет только первому
        other = Contact.objects.create(
            company=client_company, name="Colleague", email="colleague@example.uz", telegram_user_id=555, language="ru"
        )
        CrmContactMapping.objects.create(contact=other, crm_contact_id=CRM_CONTACT_ID + 1)
        link, raw = mint("invoice", invoice)
        assert link.contact_id == mapped.pk
        request_code(raw)
        (envelope,) = events_of()
        assert envelope["data"]["payload"]["erp_contact_id"] == mapped.pk
        assert envelope["data"]["payload"]["crm_contact_id"] == CRM_CONTACT_ID
        # и наоборот: ссылка колеги — код только ему
        bus_support.reset()
        link2, raw2 = mint("invoice", invoice, email=other.email, name=other.name)
        assert link2.contact_id == other.pk
        request_code(raw2)
        (second,) = events_of()
        assert second["data"]["payload"]["erp_contact_id"] == other.pk

    @pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
    def test_the_message_carries_no_document_data(self, kind, request, mapped, seller_company):
        doc = request.getfixturevalue(kind)
        _, raw = mint(kind, doc)
        request_code(raw)
        data = bus_support.real_data(events_of()[0])["payload"]
        assert set(data) == {
            "erp_contact_id",
            "crm_contact_id",
            "language",
            "kind",
            "document_kind",
            "code",
            "expires_at",
        }
        text = json.dumps(data, ensure_ascii=False)
        assert doc.number not in text and seller_company.name not in text and "/d/" not in text

    def test_resend_rules_are_unchanged_and_a_blocked_resend_sends_nothing_to_the_bot(self, invoice, mapped):
        link, raw = mint("invoice", invoice)
        assert request_code(raw).status_code == status.HTTP_202_ACCEPTED
        again = request_code(raw)
        assert again.status_code == status.HTTP_429_TOO_MANY_REQUESTS and again.json() == {
            "detail": "CODE_RESEND_TOO_SOON"
        }
        assert len(events_of()) == 1 and len(mail.outbox) == 1
        MagicLinkToken.objects.update(created_at=timezone.now() - datetime.timedelta(seconds=46))
        assert request_code(raw).status_code == status.HTTP_202_ACCEPTED
        assert len(events_of()) == 2 and len(mail.outbox) == 2
        second = bus_support.real_data(events_of()[1])["payload"]["code"]
        assert second == sent_code(), "новый код — и в письме, и в боте"
        # один активный код: прежний погашен, как раньше
        assert MagicLinkToken.objects.filter(document_link=link, used_at__isnull=True).count() == 1

    def test_a_failed_mail_leaves_no_event_for_the_bot(self, invoice, mapped, monkeypatch):
        monkeypatch.setattr(doc_links, "_send_code_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
        _, raw = mint("invoice", invoice)
        with pytest.raises(RuntimeError):
            request_code(raw)
        assert not events_of(), "код, которого нет в письме, не уходит и в бот"
        assert not MagicLinkToken.objects.filter(document_link__kind="invoice").exists()


# ── Ссылка ────────────────────────────────────────────────────────────────────────────────────────────────────────


class TestLink:
    def deliver(self, invoice):
        from crm.services.document_letters import deliver_document_letter
        from crm.services.documents import remember_pdf_state

        remember_pdf_state("invoice", invoice.pk, False)
        return deliver_document_letter("invoice", invoice.pk, invoice.deal.contact.email, invoice.deal.contact.name)

    def test_the_personal_link_goes_to_the_bot_as_one_short_message(self, invoice, mapped, seller_company):
        assert self.deliver(invoice)["status"] == "sent"
        (envelope,) = events_of()
        bus_support.assert_matches_contract(envelope, secret_masked=True)
        assert envelope["data"]["payload"]["url"] == "***", "токен ссылки в outbox — только маской"
        payload = bus_support.real_data(envelope)["payload"]
        assert payload["kind"] == "link" and payload["document_kind"] == "invoice"
        assert payload["number"] == invoice.number and payload["seller_name"] == seller_company.name
        assert "code" not in payload
        # ссылка в боте — та самая личная ссылка получателя: открывает этот счёт и привязана к этому контакту
        raw = payload["url"].split("/d/")[1]
        link = doc_links.find_link(raw)
        assert link is not None and link.contact_id == mapped.pk and link.document.pk == invoice.pk
        assert mail.outbox[-1].body.count(raw) == 1, "в письме и в боте одна и та же ссылка"

    def test_without_a_linked_telegram_only_the_mail_goes(self, invoice, client_contact, client_company):
        CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)
        CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=CRM_CONTACT_ID)
        Contact.objects.filter(pk=client_contact.pk).update(telegram_user_id=None)
        assert self.deliver(invoice)["status"] == "sent"
        assert not events_of() and len(mail.outbox) == 1

    def test_a_contact_who_muted_telegram_documents_gets_no_link_in_the_bot(self, invoice, mapped):
        Contact.objects.filter(pk=mapped.pk).update(notification_settings={"documents": {"telegram": False}})
        assert self.deliver(invoice)["status"] == "sent"
        assert not events_of() and len(mail.outbox) == 1

    def test_a_link_whose_mail_failed_is_not_sent_to_the_bot(self, invoice, mapped, monkeypatch):
        from types import SimpleNamespace

        import notifications.emails as emails
        from notifications.models import EmailLog

        monkeypatch.setattr(
            emails, "send_templated_email", lambda *a, **k: SimpleNamespace(status=EmailLog.STATUS_FAILED)
        )
        assert self.deliver(invoice)["status"] == "failed"
        assert not events_of() and not DocumentLink.objects.filter(kind="invoice", revoked_at__isnull=True).exists()

    def test_a_bot_failure_does_not_undo_the_letter(self, invoice, mapped, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("bus down")

        monkeypatch.setattr(doc_links, "send_link_telegram", boom)
        assert self.deliver(invoice)["status"] == "sent" and len(mail.outbox) == 1

    def test_the_quote_letter_sends_its_link_to_the_bot_too(self, quote, mapped, monkeypatch):
        from crm import tasks

        monkeypatch.setattr(tasks, "_render_pdf_for", lambda *a, **k: None)
        tasks.send_quote_email.apply(args=[quote.pk])
        (envelope,) = events_of()
        payload = bus_support.real_data(envelope)["payload"]
        assert payload["kind"] == "link" and payload["document_kind"] == "quote" and payload["number"] == quote.number
        raw = payload["url"].split("/d/")[1]
        assert DocumentLink.objects.get(kind="quote").token_hash == doc_links.hash_token(raw)


# ── Почта — основной канал: сбой бота не отменяет код ────────────────────────────────────────────────────────────


class TestBotFailure:
    def test_a_failed_bot_event_still_sends_the_code_by_mail(self, invoice, mapped, monkeypatch):
        from integration.services import events

        def boom(*args, **kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr(events, "publish_document_link_telegram", boom)
        link, raw = mint("invoice", invoice)
        response = request_code(raw)
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json()["channels"] == ["email"]
        assert not events_of() and len(mail.outbox) == 1
        assert MagicLinkToken.objects.filter(document_link=link, used_at__isnull=True).count() == 1
        # код из письма открывает ссылку: он действует
        verify = post("verify", {"token": raw, "code": sent_code()})
        assert verify.status_code == status.HTTP_200_OK, verify.content


# ── Одно сообщение на документ: «КП готово» не дублирует личную ссылку ───────────────────────────────────────────


class TestQuoteSentNotDuplicated:
    def publish(self, quote, channels=None):
        from django.db import transaction
        from integration.services import events

        bus_support.reset()
        with transaction.atomic():
            events.publish_quote_sent(quote, channels=channels)
        return bus_support.only("quote.sent")["data"].get("telegram_muted_user_ids", [])

    def test_the_chat_that_gets_the_personal_link_is_muted_for_the_general_message(self, quote, mapped):
        assert self.publish(quote) == [mapped.telegram_user_id]

    def test_a_chat_without_a_personal_link_keeps_the_general_message(self, quote, client_contact, client_company):
        CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)
        Contact.objects.filter(pk=client_contact.pk).update(telegram_user_id=None)
        assert self.publish(quote) == []

    def test_a_telegram_only_send_has_no_letter_and_keeps_the_general_message(self, quote, mapped):
        assert self.publish(quote, channels=["telegram"]) == []

    def test_a_contact_who_muted_telegram_documents_is_muted_once(self, quote, mapped):
        Contact.objects.filter(pk=mapped.pk).update(notification_settings={"documents": {"telegram": False}})
        assert self.publish(quote) == [mapped.telegram_user_id]  # общее «КП готово» отключено настройкой

    def test_another_contact_of_the_company_keeps_the_general_message(self, quote, mapped, client_company):
        Contact.objects.create(company=client_company, name="Other", email="o@example.uz", telegram_user_id=555)
        assert self.publish(quote) == [mapped.telegram_user_id]
