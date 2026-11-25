"""Договор, счёт и акт по ссылке получателя (ДК-3, ADR-0030): та же схема, что у КП.

Проверяются факты, от которых зависят безопасность и сценарий: ссылка привязана к получателю И к документу; отзыв гасит
все ссылки документа, но не чужие; права не шире контакта; у каждого вида — только свои действия (ссылка счёта не принимает,
ссылка договора не отвечает на вопросы КП); письма о счёте, акте и договоре идут контактам сделки, а не участникам компании
в ERP; получатель документа получает уведомления сделки без входа; отправку договора по-прежнему решает `send_blocker`.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from portal.models import DocumentLink, PortalNotice
from portal.services import doc_links, notice_sources
from portal.tests.conftest import LOCMEM_BACKEND
from portal.tests.test_doc_links import open_, post, verified_client
from rest_framework import status

from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    cache.clear()
    mail.outbox.clear()


def _status(model, code, name):
    return model.objects.get_or_create(code=code, defaults={"name": name})[0]


@pytest.fixture
def deal(client_company, client_contact):
    stage, _ = DealStage.objects.get_or_create(code=DealStageCode.CONTRACT_SIGNED, defaults={"name": "Договор"})
    return Deal.objects.create(company=client_company, contact=client_contact, title="Поставка труб", stage=stage)


@pytest.fixture
def quote(deal, seller_company):
    sent = _status(QuoteStatus, QuoteStatusCode.APPROVED, "Принято")
    return Quote.objects.create(
        deal=deal, version=1, status=sent, number="КП-1", total_incl_vat=Decimal("100"), seller_company=seller_company
    )


def _pdf(doc):
    doc.pdf_file.save("d.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    return doc


@pytest.fixture
def contract(deal, quote):
    row = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-1",
        status=_status(ContractStatus, ContractStatusCode.PENDING_CLIENT, "На подписи"),
        total_amount=Decimal("1000000"),
    )
    return _pdf(row)


@pytest.fixture
def invoice(deal, contract):
    row = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-1",
        issued_at=datetime.date.today(),
        due_date=datetime.date.today() + datetime.timedelta(days=5),
        status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED, "Выставлен"),
        total_incl_vat=Decimal("1000000"),
        frozen_bank_details="р/с 2020 8000 1234 5678 9001, МФО 00014",
    )
    return _pdf(row)


@pytest.fixture
def act(deal, contract, invoice):
    row = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-1",
        status=_status(ActStatus, ActStatusCode.ISSUED, "Выставлен"),
        total_amount=Decimal("1000000"),
    )
    return _pdf(row)


def mint(kind, doc, email=None, name="Получатель"):
    email = email or doc.deal.contact.email
    return doc_links.mint_document_link(kind, doc, email, name)


def act_(raw, action, client, text=None):
    body = {"token": raw, "action": action}
    if text is not None:
        body["text"] = text
    return post("act", body, client)


# ── Ссылка привязана к получателю и к документу ───────────────────────────────────────────────────────────────────


class TestBinding:
    @pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
    def test_link_is_bound_to_the_recipient_and_the_document(self, kind, request, client_contact):
        doc = request.getfixturevalue(kind)
        link, raw = mint(kind, doc)
        assert link.kind == kind and link.document.pk == doc.pk
        assert link.contact_id == client_contact.pk and link.recipient_email == client_contact.email
        assert not DocumentLink.objects.filter(token_hash=raw).exists()  # в базе только хеш
        body = open_(raw).json()
        assert body["kind"] == kind and body["number"] == doc.number

    def test_a_link_never_shows_another_document(self, contract, invoice, act):
        _, raw = mint("invoice", invoice)
        mint("contract", contract)
        body = open_(raw).json()
        assert body["number"] == "INV-1" and body["kind"] == "invoice"

    def test_the_database_refuses_a_link_whose_document_does_not_match_its_kind(self, contract, invoice):
        with pytest.raises(IntegrityError), transaction.atomic():
            DocumentLink.objects.create(
                token_hash="x" * 64,
                kind="invoice",
                contract=contract,
                recipient_email="a@b.uz",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc),
            )

    def test_a_recipient_outside_the_contacts_gets_no_contact(self, invoice, client_company):
        from parties.models import Contact

        before = Contact.objects.filter(company=client_company).count()
        link, raw = mint("invoice", invoice, email="finance@new.example.uz", name="Финансы")
        assert link.contact is None and Contact.objects.filter(company=client_company).count() == before
        assert post("code", {"token": raw}).status_code == 403  # кода нет: контакт заводит сотрудник


# ── Гость видит клиентскую проекцию своего вида ───────────────────────────────────────────────────────────────────


class TestGuestView:
    def test_contract_shows_key_facts_and_signing(self, contract):
        _, raw = mint("contract", contract)
        body = open_(raw).json()
        assert body["state"] == "open" and body["actions"] == ["accept"]
        assert body["total"]["amount"] and body["lines"] == []
        assert "cost" not in str(body).lower() and "margin" not in str(body).lower()

    def test_invoice_shows_payment_details_and_no_actions(self, invoice):
        _, raw = mint("invoice", invoice)
        body = open_(raw).json()
        assert body["actions"] == [] and body["decide"] == {"allowed": False, "reason": "no_actions"}
        assert "2020 8000" in body["payment_details"] and body["due_date"] == invoice.due_date.isoformat()
        assert body["balance_due"]["amount"] and body["state"] == "open"

    def test_paid_invoice_is_shown_as_paid(self, invoice):
        invoice.status = _status(InvoiceStatus, InvoiceStatusCode.PAID, "Оплачен")
        invoice.amount_paid = invoice.total_incl_vat
        invoice.save()
        _, raw = mint("invoice", invoice)
        assert open_(raw).json()["state"] == "paid"

    def test_act_offers_accept_and_return(self, act):
        _, raw = mint("act", act)
        body = open_(raw).json()
        assert body["actions"] == ["accept", "reject"] and body["state"] == "open"

    @pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
    def test_guest_downloads_the_pdf_of_this_document(self, kind, request):
        doc = request.getfixturevalue(kind)
        _, raw = mint(kind, doc)
        from crm.services import documents as pdf_documents

        pdf_documents.remember_pdf_state(kind, doc.pk, False)
        response = post("pdf", {"token": raw})
        assert response.status_code == status.HTTP_200_OK


# ── Действия: только свои, только по коду, права не шире контакта ──────────────────────────────────────────────────


class TestActions:
    def test_code_then_sign_the_contract(self, contract):
        _, raw = mint("contract", contract)
        client, _ = verified_client(raw, None)
        response = act_(raw, "accept", client)
        assert response.status_code == status.HTTP_200_OK, response.content
        contract.refresh_from_db()
        assert contract.client_signed_at is not None and contract.status.code != ContractStatusCode.PENDING_CLIENT
        assert response.json()["state"] == "accepted"

    def test_code_then_accept_the_act(self, act):
        _, raw = mint("act", act)
        client, _ = verified_client(raw, None)
        assert act_(raw, "accept", client).status_code == status.HTTP_200_OK
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.SIGNED

    def test_return_the_act_needs_remarks(self, act):
        _, raw = mint("act", act)
        client, _ = verified_client(raw, None)
        assert act_(raw, "reject", client).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert act_(raw, "reject", client, text="Не та сумма").status_code == status.HTTP_200_OK
        act.refresh_from_db()
        assert act.status.code != ActStatusCode.ISSUED and act.rejection_reason == "Не та сумма"

    def test_wrong_action_for_the_type_is_refused_and_changes_nothing(self, contract, invoice, act):
        _, contract_raw = mint("contract", contract)
        _, invoice_raw = mint("invoice", invoice)
        _, act_raw = mint("act", act)
        client, _ = verified_client(contract_raw, None)
        # у договора нет «вернуть» и «вопрос», у счёта нет ни одного действия, у акта нет «вопроса»
        for raw, action in (
            (contract_raw, "reject"),
            (contract_raw, "question"),
            (invoice_raw, "accept"),
            (act_raw, "question"),
        ):
            assert act_(raw, action, client, text="x").status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        contract.refresh_from_db()
        invoice.refresh_from_db()
        act.refresh_from_db()
        assert contract.client_signed_at is None
        assert invoice.status.code == InvoiceStatusCode.ISSUED and act.status.code == ActStatusCode.ISSUED

    def test_a_session_signed_in_by_one_link_does_not_act_on_another_document_through_a_wrong_token(
        self, contract, act
    ):
        _, contract_raw = mint("contract", contract)
        _, act_raw = mint("act", act)
        client, _ = verified_client(contract_raw, None)
        # токен акта + действие акта: сессия контакта той же компании действует (тот же контакт), но над АКТОМ, не договором
        assert act_(act_raw, "accept", client).status_code == status.HTTP_200_OK
        contract.refresh_from_db()
        assert contract.client_signed_at is None

    def test_rights_are_not_wider_than_the_contacts(self, act, readonly_contact):
        link, raw = mint("act", act, email=readonly_contact.email)
        body = open_(raw).json()
        assert body["decide"] == {"allowed": False, "reason": "no_right"}
        client, _ = verified_client(raw, None)
        assert act_(raw, "accept", client).status_code == status.HTTP_403_FORBIDDEN
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.ISSUED

    def test_the_module_of_the_type_is_required_for_the_action(self, act, monkeypatch):
        import portal.authentication as authentication

        _, raw = mint("act", act)
        client, _ = verified_client(raw, None)
        real = authentication.access_from_row
        monkeypatch.setattr(
            authentication,
            "access_from_row",
            lambda session: (lambda roles, modules: (roles, [m for m in modules if m != "acts"]))(*real(session)),
        )
        assert act_(raw, "accept", client).status_code == status.HTTP_403_FORBIDDEN
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.ISSUED

    def test_another_company_session_cannot_act_by_a_forwarded_link(self, act, other_session):
        from portal.tests.test_doc_links import session_client

        _, raw = mint("act", act)
        assert act_(raw, "accept", session_client(other_session)).status_code == status.HTTP_403_FORBIDDEN
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.ISSUED

    def test_decided_act_cannot_be_decided_again(self, act):
        _, raw = mint("act", act)
        client, _ = verified_client(raw, None)
        assert act_(raw, "accept", client).status_code == status.HTTP_200_OK
        assert act_(raw, "accept", client).status_code == status.HTTP_409_CONFLICT


# ── Отзыв и состояние из фактов ───────────────────────────────────────────────────────────────────────────────────


class TestRevokeAndFacts:
    def test_revoking_the_document_kills_every_recipient_link_and_only_this_documents(self, invoice, act):
        _, first = mint("invoice", invoice)
        _, second = mint("invoice", invoice, email="finance@new.example.uz")
        _, other = mint("act", act)
        assert doc_links.revoke_document_links("invoice", invoice, None) == 2
        for raw in (first, second):
            response = open_(raw)
            assert response.status_code == status.HTTP_410_GONE and response.json()["detail"] == "DOC_LINK_REVOKED"
        assert open_(other).status_code == status.HTTP_200_OK
        assert doc_links.revoke_document_links("invoice", invoice, None) == 0

    def test_revoking_one_invoice_leaves_the_links_of_another_invoice_alone(self, invoice, deal, contract):
        second = Invoice.objects.create(
            deal=deal,
            contract=contract,
            number="INV-2",
            issued_at=datetime.date.today(),
            due_date=datetime.date.today() + datetime.timedelta(days=5),
            status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED, "Выставлен"),
            total_incl_vat=Decimal("5"),
        )
        _, first_raw = mint("invoice", invoice)
        _, second_raw = mint("invoice", second)
        assert doc_links.revoke_document_links("invoice", invoice, None) == 1
        assert open_(first_raw).status_code == status.HTTP_410_GONE
        assert open_(second_raw).status_code == status.HTTP_200_OK

    def test_revoked_link_cannot_act_even_with_a_live_session(self, act):
        _, raw = mint("act", act)
        client, _ = verified_client(raw, None)
        doc_links.revoke_document_links("act", act, None)
        assert act_(raw, "accept", client).status_code == status.HTTP_410_GONE
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.ISSUED

    def test_a_new_link_after_the_revoke_is_live(self, invoice):
        mint("invoice", invoice)
        doc_links.revoke_document_links("invoice", invoice, None)
        _, raw = mint("invoice", invoice)
        assert open_(raw).status_code == status.HTTP_200_OK

    def test_contract_returned_to_draft_is_not_shown(self, contract):
        _, raw = mint("contract", contract)
        contract.status = _status(ContractStatus, ContractStatusCode.DRAFT, "Черновик")
        contract.save()
        assert open_(raw).status_code == status.HTTP_410_GONE

    def test_cancelled_invoice_and_act_are_not_shown(self, invoice, act):
        _, invoice_raw = mint("invoice", invoice)
        _, act_raw = mint("act", act)
        invoice.status = _status(InvoiceStatus, InvoiceStatusCode.CANCELLED, "Отменён")
        invoice.save()
        act.status = _status(ActStatus, ActStatusCode.CANCELLED, "Отменён")
        act.save()
        assert open_(invoice_raw).status_code == status.HTTP_410_GONE
        assert open_(act_raw).status_code == status.HTTP_410_GONE

    def test_returned_act_shows_the_state_returned(self, act):
        _, raw = mint("act", act)
        act.status = _status(ActStatus, ActStatusCode.DRAFT, "Черновик")
        act.rejection_reason = "Не та сумма"
        act.save()
        assert open_(raw).json()["state"] == "rejected"

    def test_expired_link_shows_only_the_reason(self, invoice):
        link, raw = mint("invoice", invoice)
        DocumentLink.objects.filter(pk=link.pk).update(
            expires_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        )
        response = open_(raw)
        assert response.status_code == status.HTTP_410_GONE and response.json()["detail"] == "DOC_LINK_EXPIRED"


# ── Письма: контактам сделки, с PDF и одной кнопкой ───────────────────────────────────────────────────────────────


class TestLetters:
    @pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
    def test_the_letter_has_the_pdf_and_one_personal_link_of_this_document(self, kind, request, client_contact):
        from crm.services.document_letters import deliver_document_letter
        from crm.services.documents import remember_pdf_state

        doc = request.getfixturevalue(kind)
        remember_pdf_state(kind, doc.pk, False)
        result = deliver_document_letter(kind, doc.pk, client_contact.email, client_contact.name)
        assert result["status"] == "sent"
        message = mail.outbox[-1]
        assert message.to == [client_contact.email] and len(message.attachments) == 1
        link = DocumentLink.objects.get(kind=kind)
        assert link.document.pk == doc.pk and link.contact_id == client_contact.pk
        token = message.body.split("/d/")[1].split()[0]
        assert link.token_hash and open_(token).json()["number"] == doc.number
        assert message.body.count("/d/") == 1

    def test_the_letter_is_not_sent_for_a_document_the_client_does_not_see(self, invoice, client_contact):
        from crm.services.document_letters import deliver_document_letter

        invoice.status = _status(InvoiceStatus, InvoiceStatusCode.CANCELLED, "Отменён")
        invoice.save()
        assert (
            deliver_document_letter("invoice", invoice.pk, client_contact.email, "x")["status"] == "skipped_not_visible"
        )
        assert not mail.outbox

    def test_letters_go_to_deal_contacts_not_to_company_members(
        self, invoice, client_company, client_contact, monkeypatch, django_capture_on_commit_callbacks
    ):
        from accounts.models import CompanyMember, CustomUser, WorkspaceRole
        from crm import tasks
        from crm.services.deal_emails import email_invoice_issued

        user = CustomUser.objects.create_user(username="old.member", email="old.member@example.uz", password="x")
        CompanyMember.objects.create(
            user=user, company=client_company, role=WorkspaceRole.objects.get(code="MEMBER"), is_active=True
        )
        sent = []
        monkeypatch.setattr(tasks.send_document_link_email, "delay", lambda *args: sent.append(args))
        with django_capture_on_commit_callbacks(execute=True):
            email_invoice_issued(invoice)
        assert [item[2] for item in sent] == [client_contact.email]

    def test_recipients_are_the_deal_contact_and_contacts_who_got_a_document(
        self, deal, invoice, client_contact, client_company
    ):
        from parties.models import Contact

        Contact.objects.create(company=client_company, name="Финансы", email="finance@new.example.uz")
        mint("invoice", invoice, email="finance@new.example.uz", name="Финансы")
        emails = [email for email, _ in doc_links.deal_recipients(deal)]
        assert emails == [client_contact.email, "finance@new.example.uz"]

    def test_a_typo_or_forwarded_address_does_not_receive_the_next_documents(self, deal, invoice, client_contact):
        """В-1: ссылка без контакта живёт, но адрес получателем следующих документов и писем сделки не становится."""
        link, _ = mint("invoice", invoice, email="typo@stranger.example", name="Опечатка")
        assert link.contact is None
        emails = [email for email, _ in doc_links.deal_recipients(deal)]
        assert emails == [client_contact.email]
        assert "typo@stranger.example" not in emails

    def test_a_deal_without_a_chosen_contact_falls_back_to_the_primary_contact(self, deal, client_contact):
        deal.contact = None
        deal.save()
        client_contact.is_primary = True
        client_contact.save()
        assert [email for email, _ in doc_links.deal_recipients(deal)] == [client_contact.email]


# ── Получатель документа получает уведомления сделки без входа ────────────────────────────────────────────────────


class TestNotificationsForRecipients:
    def test_a_document_recipient_who_never_signed_in_gets_the_deals_letters(self, invoice, deal, client_company):
        from parties.models import Contact
        from portal.models import NoticeChannel
        from portal.services import notices

        recipient = Contact.objects.create(
            company=client_company, name="Финансы", email="finance@new.example.uz", can_act=False
        )
        link, _ = mint("invoice", invoice, email="finance@new.example.uz", name="Финансы")
        assert link.contact == recipient
        assert recipient.invited_at is None and recipient.last_login_at is None
        assert recipient.pk != deal.contact_id
        # следующее событие сделки (сдвиг срока поставки) — письмо получателю документа, хотя в кабинет он не входил
        notices.notify(
            "delivery_eta_changed",
            company=client_company,
            object_id=deal.pk,
            link=f"/deals/{deal.pk}",
            dedup="eta-1",
            bot_reaches=False,
            document_contact_ids=notice_sources._document_contacts(deal),
        )
        notice = PortalNotice.objects.get(contact=recipient, kind="delivery_eta_changed")
        assert notice.channel == NoticeChannel.EMAIL and notice.email_reason == ""

    def test_a_revoked_recipient_gets_no_further_letters_or_deal_notifications(self, invoice, deal, client_company):
        from parties.models import Contact
        from portal.services import notices

        wrong = Contact.objects.create(
            company=client_company, name="Не тот", email="wrong.person@example.uz", can_act=False
        )
        link, _ = mint("invoice", invoice, email="wrong.person@example.uz", name="Не тот")
        assert link.contact == wrong
        assert "wrong.person@example.uz" in [email for email, _ in doc_links.deal_recipients(deal)]
        doc_links.revoke_document_links("invoice", invoice, None)
        assert "wrong.person@example.uz" not in [email for email, _ in doc_links.deal_recipients(deal)]
        assert wrong.pk not in doc_links.document_contact_ids(deal)
        notices.notify(
            "delivery_eta_changed",
            company=client_company,
            object_id=deal.pk,
            link=f"/deals/{deal.pk}",
            dedup="eta-revoked",
            bot_reaches=False,
            document_contact_ids=notice_sources._document_contacts(deal),
        )
        assert PortalNotice.objects.get(contact=wrong, kind="delivery_eta_changed").email_reason == "not_invited"

    def test_a_contact_who_got_no_document_is_still_not_invited(self, invoice, client_company):
        from parties.models import Contact

        stranger = Contact.objects.create(
            company=client_company, name="Чужой", email="stranger@example.uz", can_act=True
        )
        notice_sources.payment_overdue(invoice, bot_reaches=False)
        assert PortalNotice.objects.get(contact=stranger, kind="payment_overdue").email_reason == "not_invited"


# ── Договор: отправку по-прежнему решает send_blocker ────────────────────────────────────────────────────────────


class TestContractSendDecision:
    def test_the_letter_goes_only_when_send_blocker_allows_the_send(self, contract, monkeypatch):
        from crm.services import contract_flow, document_letters

        contract.status = _status(ContractStatus, ContractStatusCode.DRAFT, "Черновик")
        contract.save()
        sent = []
        monkeypatch.setattr(document_letters, "email_document", lambda kind, doc, **kw: sent.append((kind, doc.pk)))

        monkeypatch.setattr(contract_flow, "send_blocker", lambda c: {"code": "CONTRACT_DEVIATION_PENDING"})
        _, error = contract_flow.apply_transition(contract.pk, "send_to_client", None)
        assert error and sent == []

        monkeypatch.setattr(contract_flow, "send_blocker", lambda c: None)
        _, error = contract_flow.apply_transition(contract.pk, "send_to_client", None)
        assert error is None and sent == [("contract", contract.pk)]


class TestUndeliveredLink:
    def test_a_letter_that_was_not_handed_to_the_mail_service_leaves_no_live_link(
        self, invoice, client_contact, monkeypatch
    ):
        from types import SimpleNamespace

        import notifications.emails as emails
        from crm.services.document_letters import deliver_document_letter
        from crm.services.documents import remember_pdf_state
        from notifications.models import EmailLog

        remember_pdf_state("invoice", invoice.pk, False)
        monkeypatch.setattr(
            emails, "send_templated_email", lambda *a, **k: SimpleNamespace(status=EmailLog.STATUS_FAILED)
        )
        result = deliver_document_letter("invoice", invoice.pk, client_contact.email, "x")
        assert result["status"] == "failed"
        assert not DocumentLink.objects.filter(kind="invoice", revoked_at__isnull=True).exists()
