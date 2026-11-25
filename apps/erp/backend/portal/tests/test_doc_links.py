"""Документ по ссылке из письма (ДК-1, ДК-2, ADR-0030): гость видит один документ, действие — по коду, код — вход.

Проверяются факты, от которых зависит безопасность и сценарий: токен в базе только хешем и привязан к получателю; пересланная
ссылка не даёт действовать никому, кроме того, кто получает письма на адрес получателя; отозванная, просроченная и
заменённая ссылки показывают только причину; код — шесть цифр на десять минут, пять попыток, повтор не раньше 45 секунд, чужой
ссылки код не гасит; права сессии не шире прав контакта; действие после кода идёт без второго клика и второго кода.
"""

from __future__ import annotations

import datetime
import re
import uuid
from decimal import Decimal

import pytest
from django.conf import settings as dj_settings
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone
from portal.models import DocumentLink, DocumentLinkEvent, MagicLinkToken, PortalSession
from portal.services import doc_links
from portal.services.tokens import hash_token
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient
from rest_framework import status

from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus

BASE = "/api/portal/v1/doc-links"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    cache.clear()
    mail.outbox.clear()


@pytest.fixture
def quote(client_company, client_contact, seller_company):
    stage, _ = DealStage.objects.get_or_create(code=DealStageCode.QUOTE_SENT, defaults={"name": "КП отправлено"})
    sent, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
    deal = Deal.objects.create(company=client_company, contact=client_contact, title="Поставка труб", stage=stage)
    item = Quote.objects.create(
        deal=deal,
        version=1,
        status=sent,
        number="КП-2026-001",
        total_incl_vat=Decimal("412500000"),
        valid_until=timezone.localdate() + datetime.timedelta(days=10),
        frozen_at=timezone.now(),
        public_access_token=uuid.uuid4().hex,
        seller_company=seller_company,
    )
    item.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    return item


@pytest.fixture
def minted(quote):
    link, raw = doc_links.mint_quote_link(quote)
    return link, raw


def post(path, data=None, client=None, **extra):
    return (client or PortalAPIClient()).post(f"{BASE}/{path}", data or {}, format="json", **extra)


def open_(raw, client=None):
    return post("open", {"token": raw}, client)


def sent_code() -> str:
    return re.search(r"(\d{6})", mail.outbox[-1].body).group(1)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def session_client(session) -> PortalAPIClient:
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


def verified_client(raw, link):
    """Гость → код на почту получателя → `verify`: клиент с cookie сессии контакта."""
    assert post("code", {"token": raw}).status_code == status.HTTP_202_ACCEPTED
    client = PortalAPIClient()
    response = post("verify", {"token": raw, "code": sent_code()}, client)
    assert response.status_code == status.HTTP_200_OK, response.content
    return client, response


# ── ДК-1: выпуск и просмотр гостем ────────────────────────────────────────────────────────────────────────────────


class TestMint:
    def test_token_is_stored_only_as_a_hash_and_bound_to_the_recipient(self, quote, minted, client_contact):
        link, raw = minted
        assert link.token_hash == hash_token(raw) and raw not in link.token_hash
        assert not DocumentLink.objects.filter(token_hash=raw).exists()
        assert link.recipient_email == client_contact.email and link.contact_id == client_contact.pk
        assert doc_links.build_url(raw) == f"http://cabinet.localhost/d/{raw}"

    def test_expiry_is_valid_until_plus_thirty_days(self, quote, minted):
        link, _ = minted
        expected = quote.valid_until + datetime.timedelta(days=doc_links.LINK_GRACE_DAYS)
        assert timezone.localtime(link.expires_at).date() == expected

    def test_each_send_gets_its_own_token(self, quote):
        first, raw1 = doc_links.mint_quote_link(quote)
        second, raw2 = doc_links.mint_quote_link(quote)
        assert raw1 != raw2 and first.pk != second.pk

    def test_a_recipient_without_a_contact_stays_a_guest_of_that_one_document(self, quote, client_company):
        """В-1 (ADR-0030 п. 7, поправка 2026-11-25): адрес получателя контактом не становится; гость — один документ."""
        from parties.models import Contact

        from accounts.models import CustomUser

        buyer = CustomUser.objects.create_user(
            username="new.buyer", email="new.buyer@example.uz", password="x", first_name="Buyer"
        )
        quote.deal.contact = None
        quote.deal.client = buyer
        quote.deal.save()
        before = Contact.objects.filter(company=client_company).count()
        link, raw = doc_links.mint_quote_link(quote)
        assert link.contact is None and link.recipient_email == "new.buyer@example.uz"
        assert Contact.objects.filter(company=client_company).count() == before
        # просмотр и PDF — по ссылке, без входа; действий нет, причина названа
        body = open_(raw).json()
        assert body["session"] == "none" and body["decide"] == {"allowed": False, "reason": "no_contact"}
        assert post("pdf", {"token": raw}).status_code == status.HTTP_200_OK
        # кода и сессии нет: войти в кабинет по такой ссылке нельзя
        mail.outbox.clear()
        assert post("code", {"token": raw}).status_code == status.HTTP_403_FORBIDDEN
        assert post("verify", {"token": raw, "code": "123456"}).status_code == status.HTTP_403_FORBIDDEN
        assert not mail.outbox and not MagicLinkToken.objects.filter(document_link=link).exists()
        assert not PortalSession.objects.exists()
        assert post("act", {"token": raw, "action": "accept"}).status_code in (401, 403)
        # отзыв ссылки заканчивает гостевой доступ
        doc_links.revoke_quote_links(quote, None)
        assert open_(raw).status_code == status.HTTP_410_GONE
        assert post("pdf", {"token": raw}).status_code == status.HTTP_410_GONE
        # вход по ссылке на почту такому адресу тоже не выпускается: контакта нет
        from portal.services.magic_link import find_login_contact

        assert find_login_contact("new.buyer@example.uz") is None

    def test_old_auto_created_contacts_are_listed_read_only(self, quote, client_company):
        """Контакт, заведённый прежним выпуском ссылок, попадает в список для владельца; назначенные и с правами — нет."""
        from io import StringIO

        from django.core.management import call_command
        from parties.models import Contact

        auto = Contact.objects.create(company=client_company, name="a@x.example", email="a@x.example", can_act=False)
        DocumentLink.objects.create(
            token_hash=hash_token("old"),
            kind="quote",
            quote=quote,
            contact=auto,
            recipient_email="a@x.example",
            expires_at=timezone.now() + datetime.timedelta(days=5),
        )
        rows = doc_links.auto_created_document_contacts()
        assert [row["contact_id"] for row in rows] == [auto.pk]
        assert not [row for row in rows if row["email"] == quote.deal.contact.email]  # контакт заявки — не авто
        out = StringIO()
        call_command("list_auto_document_contacts", stdout=out)
        assert "a@x.example" in out.getvalue() and Contact.objects.filter(pk=auto.pk).exists()

    def test_a_guest_link_opens_no_other_part_of_the_cabinet(self, quote):
        """Гость по ссылке без контакта не листает ни КП, ни счета, ни документы, ни команду, ни чат."""
        from accounts.models import CustomUser

        buyer = CustomUser.objects.create_user(username="guest.b", email="guest.b@example.uz", password="x")
        quote.deal.contact = None
        quote.deal.client = buyer
        quote.deal.save()
        _, raw = doc_links.mint_quote_link(quote)
        guest = PortalAPIClient()
        assert open_(raw, guest).status_code == status.HTTP_200_OK
        for path in ("quotes", "invoices", "documents", "team", "messages", "contracts", "acts"):
            response = guest.get(f"/api/portal/v1/{path}")
            assert response.status_code == status.HTTP_401_UNAUTHORIZED, path
        assert guest.get(f"/api/portal/v1/quotes/{quote.pk}").status_code == status.HTTP_401_UNAUTHORIZED

    def test_the_send_task_mails_a_cabinet_link_not_the_erp_page(self, quote, monkeypatch):
        from crm import tasks

        monkeypatch.setattr(tasks, "_render_pdf_for", lambda *a, **k: None)
        tasks.send_quote_email.apply(args=[quote.pk])

        body = mail.outbox[-1].body
        assert "http://cabinet.localhost/d/" in body and "/api/v1/public/quotes/" not in body
        raw = re.search(r"/d/([\w-]+)", body).group(1)
        assert DocumentLink.objects.get(token_hash=hash_token(raw)).quote_id == quote.pk


class TestGuestView:
    def test_guest_sees_only_this_document_in_the_client_projection(self, quote, minted, client_company):
        _, raw = minted
        response = open_(raw)

        assert response.status_code == status.HTTP_200_OK, response.content
        data = response.json()
        assert data["number"] == "КП-2026-001" and data["to_name"] == client_company.name
        assert data["total"]["amount"] == "412500000.00" and data["state"] == "open" and data["session"] == "none"
        text = response.content.decode()
        for forbidden in ("margin", "cost", "landed", "public_access_token", "azamat.client@example.uz"):
            assert forbidden not in text
        assert data["recipient_hint"] == "a***@example.uz"

    def test_guest_gets_pdf(self, quote, minted):
        _, raw = minted
        response = post("pdf", {"token": raw})
        assert response.status_code == status.HTTP_200_OK
        assert b"".join(response.streaming_content).startswith(b"%PDF")

    def test_open_is_audited(self, quote, minted):
        link, raw = minted
        open_(raw)
        open_(raw)
        link.refresh_from_db()
        assert link.open_count == 2 and link.first_opened_at is not None
        assert DocumentLinkEvent.objects.filter(link=link, event="opened").count() == 2

    def test_unknown_tokens_get_one_and_the_same_answer(self, quote, minted):
        first = open_("a" * 43)
        second = open_(minted[1][:-1] + ("A" if minted[1][-1] != "A" else "B"))
        assert first.status_code == second.status_code == status.HTTP_404_NOT_FOUND
        assert first.json() == second.json() == {"detail": "NOT_FOUND"}

    @pytest.mark.parametrize("path", ["open", "pdf", "code"])
    def test_every_public_endpoint_hides_unknown_tokens(self, path):
        assert post(path, {"token": "x" * 43}).status_code == status.HTTP_404_NOT_FOUND

    def test_revoked_link_shows_only_the_reason(self, quote, minted):
        link, raw = minted
        link.revoked_at = timezone.now()
        link.save()
        response = open_(raw)
        assert response.status_code == status.HTTP_410_GONE
        assert response.json() == {"detail": "DOC_LINK_REVOKED"}
        assert post("pdf", {"token": raw}).status_code == status.HTTP_410_GONE
        assert post("code", {"token": raw}).status_code == status.HTTP_410_GONE
        assert not mail.outbox

    def test_expired_link_shows_only_the_reason(self, quote, minted):
        link, raw = minted
        DocumentLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        response = open_(raw)
        assert response.status_code == status.HTTP_410_GONE and response.json() == {"detail": "DOC_LINK_EXPIRED"}

    def test_a_newer_sent_version_supersedes_the_link(self, quote, minted):
        _, raw = minted
        Quote.objects.create(deal=quote.deal, version=2, status=quote.status, frozen_at=timezone.now())
        response = open_(raw)
        assert response.status_code == status.HTTP_410_GONE and response.json() == {"detail": "DOC_LINK_SUPERSEDED"}

    def test_a_returned_to_draft_quote_is_not_shown(self, quote, minted):
        _, raw = minted
        Quote.objects.filter(pk=quote.pk).update(frozen_at=None)
        assert open_(raw).status_code == status.HTTP_410_GONE

    def test_foreign_session_sees_the_guest_view(self, quote, minted, other_session):
        _, raw = minted
        data = open_(raw, session_client(other_session)).json()
        assert data["session"] == "other_company" and data["decide"] == {"allowed": False, "reason": "other_company"}

    def test_open_body_rejects_extra_keys(self, minted):
        assert post("open", {"token": minted[1], "email": "x@y.uz"}).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ── ДК-2: код ─────────────────────────────────────────────────────────────────────────────────────────────────────


class TestCode:
    def test_code_goes_only_to_the_recipient_address(self, quote, minted, client_contact):
        link, raw = minted
        response = post("code", {"token": raw})
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json() == {
            "sent_to": "a***@example.uz",
            "expires_in": 600,
            "resend_after": 45,
            "channels": ["email"],
        }
        assert [m.to for m in mail.outbox] == [[client_contact.email]]
        assert "Код" in mail.outbox[-1].subject or "code" in mail.outbox[-1].subject.lower()

    def test_the_address_cannot_be_chosen_by_the_caller(self, minted):
        response = post("code", {"token": minted[1], "email": "attacker@evil.test"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and not mail.outbox

    def test_code_is_stored_only_as_a_hash_for_ten_minutes(self, quote, minted):
        link, raw = minted
        post("code", {"token": raw})
        code = sent_code()
        row = MagicLinkToken.objects.get(document_link=link)
        assert code not in row.code_hash and row.purpose == "document"
        assert abs((row.expires_at - row.created_at) - datetime.timedelta(minutes=10)) < datetime.timedelta(seconds=2)
        assert _logs().exists() and all(code not in log.body_text for log in _logs())

    def test_resend_not_sooner_than_45_seconds(self, minted):
        raw = minted[1]
        assert post("code", {"token": raw}).status_code == status.HTTP_202_ACCEPTED
        again = post("code", {"token": raw})
        assert again.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert again.json() == {"detail": "CODE_RESEND_TOO_SOON"} and 1 <= int(again["Retry-After"]) <= 45
        assert len(mail.outbox) == 1
        MagicLinkToken.objects.update(created_at=timezone.now() - datetime.timedelta(seconds=46))
        assert post("code", {"token": raw}).status_code == status.HTTP_202_ACCEPTED

    def test_hourly_cap_per_link(self, minted):
        link, raw = minted
        for _ in range(doc_links.CODE_MAX_PER_HOUR):
            assert post("code", {"token": raw}).status_code == status.HTTP_202_ACCEPTED
            MagicLinkToken.objects.filter(document_link=link).update(
                created_at=timezone.now() - datetime.timedelta(seconds=50)
            )
        assert post("code", {"token": raw}).json() == {"detail": "TOO_MANY_REQUESTS"}

    def test_a_new_code_kills_the_previous_one(self, minted, monkeypatch):
        link, raw = minted
        codes = iter(["111111", "222222"])
        monkeypatch.setattr(doc_links, "generate_login_code", lambda: next(codes))
        post("code", {"token": raw})
        MagicLinkToken.objects.update(created_at=timezone.now() - datetime.timedelta(seconds=50))
        post("code", {"token": raw})

        assert MagicLinkToken.objects.filter(document_link=link, used_at__isnull=True).count() == 1
        assert post("verify", {"token": raw, "code": "111111"}).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert post("verify", {"token": raw, "code": "222222"}).status_code == status.HTTP_200_OK

    def test_wrong_code_is_rejected_and_five_in_a_row_lock_the_right_one(self, minted):
        link, raw = minted
        post("code", {"token": raw})
        code = sent_code()
        for _ in range(doc_links.CODE_MAX_ATTEMPTS - 1):
            response = post("verify", {"token": raw, "code": wrong(code)})
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
            assert response.json() == {"detail": "LOGIN_CODE_INVALID"}
        assert post("verify", {"token": raw, "code": wrong(code)}).json() == {"detail": "LOGIN_CODE_LOCKED"}
        assert post("verify", {"token": raw, "code": code}).status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert not PortalSession.objects.exists()
        assert DocumentLinkEvent.objects.filter(link=link, event="code_failed").count() == doc_links.CODE_MAX_ATTEMPTS

    def test_expired_code_is_rejected(self, minted):
        link, raw = minted
        post("code", {"token": raw})
        MagicLinkToken.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        response = post("verify", {"token": raw, "code": sent_code()})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and not PortalSession.objects.exists()

    def test_code_of_another_link_does_not_open_this_one(self, quote, minted, client_contact):
        _, raw = minted
        other_link, other_raw = doc_links.mint_quote_link(quote)
        post("code", {"token": other_raw})
        code = sent_code()
        response = post("verify", {"token": raw, "code": code})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and not PortalSession.objects.exists()
        assert post("verify", {"token": other_raw, "code": code}).status_code == status.HTTP_200_OK

    def test_code_is_not_a_login_code_of_the_ordinary_sign_in(self, minted, client_contact):
        _, raw = minted
        post("code", {"token": raw})
        response = PortalAPIClient().post(
            "/api/portal/v1/auth/code", {"email": client_contact.email, "code": sent_code()}, format="json"
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and not PortalSession.objects.exists()

    def test_code_is_single_use(self, minted):
        _, raw = minted
        post("code", {"token": raw})
        code = sent_code()
        assert post("verify", {"token": raw, "code": code}).status_code == status.HTTP_200_OK
        assert post("verify", {"token": raw, "code": code}).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_a_recipient_without_a_contact_cannot_get_a_code(self, quote, minted):
        link, raw = minted
        DocumentLink.objects.filter(pk=link.pk).update(contact=None)
        assert post("code", {"token": raw}).status_code == status.HTTP_403_FORBIDDEN and not mail.outbox

    def test_a_failed_mail_leaves_no_live_code(self, minted, monkeypatch):
        link, raw = minted
        monkeypatch.setattr(doc_links, "_send_code_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
        with pytest.raises(RuntimeError):
            post("code", {"token": raw})
        assert not MagicLinkToken.objects.filter(document_link=link).exists()


def _logs():
    from notifications.models import EmailLog

    return EmailLog.objects.filter(template="document_link_code")


# ── код — это вход ────────────────────────────────────────────────────────────────────────────────────────────────


class TestCodeIsLogin:
    def test_the_code_opens_the_recipients_session_with_the_rights_of_the_contact(self, minted, client_contact):
        link, raw = minted
        client, response = verified_client(raw, link)
        me = response.json()
        assert me["contact"]["id"] == client_contact.pk and me["can_act"] is True
        assert dj_settings.PORTAL_SESSION_COOKIE_NAME in response.cookies
        assert PortalSession.objects.get().contact_id == client_contact.pk
        client_contact.refresh_from_db()
        assert client_contact.invited_at is not None

    def test_rights_are_not_wider_than_the_contacts(self, quote, readonly_contact):
        quote.deal.contact = readonly_contact
        quote.deal.save()
        link, raw = doc_links.mint_quote_link(quote)
        guest = open_(raw).json()
        assert guest["decide"] == {"allowed": False, "reason": "no_right"}
        client, response = verified_client(raw, link)
        me = response.json()
        assert me["can_act"] is False and me.get("is_admin", False) is False
        assert client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json").status_code == 403
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.SENT

    def test_session_keeps_the_legal_gate(self, minted):
        from portal.services import legal

        for draft in legal.LegalEdition.objects.filter(published_at__isnull=True):
            legal.release_edition(draft.pk, actor=None)
        link, raw = minted
        client, response = verified_client(raw, link)
        assert response.json()["legal_pending"] is True
        act = client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        assert act.status_code == status.HTTP_403_FORBIDDEN and act.json() == {"detail": "LEGAL_ACCEPTANCE_REQUIRED"}


# ── действие после кода ───────────────────────────────────────────────────────────────────────────────────────────


class TestActions:
    def test_code_then_accept_without_a_second_code(self, quote, minted):
        link, raw = minted
        client, _ = verified_client(raw, link)
        response = client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["state"] == "accepted" and response.json()["session"] == "member"
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.APPROVED
        assert DocumentLinkEvent.objects.filter(link=link, event="action", action="accept").exists()

    def test_reject_needs_remarks_and_returns_the_quote(self, quote, minted):
        link, raw = minted
        client, _ = verified_client(raw, link)
        empty = client.post(f"{BASE}/act", {"token": raw, "action": "reject", "text": " "}, format="json")
        assert empty.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and empty.json()["detail"] == "REASON_REQUIRED"
        response = client.post(
            f"{BASE}/act", {"token": raw, "action": "reject", "text": "Срок поставки велик"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK and response.json()["state"] == "rejected"

    def test_question_is_written_to_the_manager_and_does_not_decide(self, quote, minted):
        link, raw = minted
        client, _ = verified_client(raw, link)
        response = client.post(
            f"{BASE}/act", {"token": raw, "action": "question", "text": "Есть ли скидка?"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK and response.json()["state"] == "open"
        assert quote.client_comments.filter(text="Есть ли скидка?").exists()

    def test_an_existing_session_of_the_same_company_acts_without_a_code(self, quote, minted, client_session):
        _, raw = minted
        client = session_client(client_session)
        assert open_(raw, client).json()["session"] == "member"
        response = client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        assert response.status_code == status.HTTP_200_OK and not _logs().exists()

    def test_action_without_a_session_is_refused(self, quote, minted):
        _, raw = minted
        response = post("act", {"token": raw, "action": "accept"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.SENT

    def test_another_company_session_cannot_act_by_a_forwarded_link(self, quote, minted, other_session):
        _, raw = minted
        response = session_client(other_session).post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.SENT

    def test_a_forwarded_link_gives_the_forwardee_nothing_without_the_recipients_mailbox(self, quote, minted):
        """Пересланная ссылка: код уходит получателю, а не тому, кто её открыл; чужой угаданный код не подходит."""
        _, raw = minted
        post("code", {"token": raw})
        guess = wrong(sent_code())
        forwardee = PortalAPIClient()
        assert post("verify", {"token": raw, "code": guess}, forwardee).status_code == 422
        assert forwardee.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json").status_code == 401
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.SENT

    def test_decided_quote_cannot_be_decided_again(self, quote, minted):
        link, raw = minted
        client, _ = verified_client(raw, link)
        client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        again = client.post(f"{BASE}/act", {"token": raw, "action": "reject", "text": "x"}, format="json")
        assert again.status_code == status.HTTP_409_CONFLICT and again.json() == {"detail": "QUOTE_FINALIZED"}
        assert open_(raw, client).json()["decide"] == {"allowed": False, "reason": "accepted"}

    def test_audit_trail_covers_open_code_and_action(self, quote, minted):
        link, raw = minted
        open_(raw)
        client, _ = verified_client(raw, link)
        client.post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        events = list(DocumentLinkEvent.objects.filter(link=link).values_list("event", flat=True))
        assert events == ["opened", "code_sent", "code_used", "action"]
        codes = set(ActivityLog.objects.filter(deal=quote.deal).values_list("event_code", flat=True))
        assert {"quote.link_code_sent", "quote.link_code_used"} <= codes


# ── отзыв отправителем ────────────────────────────────────────────────────────────────────────────────────────────


class TestRevoke:
    def test_revoking_the_document_kills_every_recipient_link(self, quote, minted):
        from accounts.models import CustomUser
        from crm.services.quotes import QuoteLifecycleService

        link, raw = minted
        second, second_raw = doc_links.mint_quote_link(quote)
        staff = CustomUser.objects.create_user(username="seller", email="seller@example.uz", password="x")
        QuoteLifecycleService.revoke_public_link(quote.pk, staff)

        for token in (raw, second_raw):
            assert open_(token).json() == {"detail": "DOC_LINK_REVOKED"}
            assert post("code", {"token": token}).status_code == status.HTTP_410_GONE
        assert DocumentLinkEvent.objects.filter(event="revoked").count() == 2
        assert not mail.outbox

    def test_revoked_link_cannot_act_even_with_a_live_session(self, quote, minted, client_session):
        from accounts.models import CustomUser
        from crm.services.quotes import QuoteLifecycleService

        _, raw = minted
        staff = CustomUser.objects.create_user(username="seller", email="seller@example.uz", password="x")
        QuoteLifecycleService.revoke_public_link(quote.pk, staff)
        response = session_client(client_session).post(f"{BASE}/act", {"token": raw, "action": "accept"}, format="json")
        assert response.status_code == status.HTTP_410_GONE
        quote.refresh_from_db()
        assert quote.status.code == QuoteStatusCode.SENT

    def test_a_link_minted_after_the_revoke_is_live(self, quote, minted):
        from accounts.models import CustomUser
        from crm.services.quotes import QuoteLifecycleService

        staff = CustomUser.objects.create_user(username="seller", email="seller@example.uz", password="x")
        QuoteLifecycleService.revoke_public_link(quote.pk, staff)
        _, fresh = doc_links.mint_quote_link(quote)
        assert open_(fresh).status_code == status.HTTP_200_OK

    def test_summary_for_the_sender(self, quote, minted):
        link, raw = minted
        open_(raw)
        quote.refresh_from_db()
        summary = doc_links.client_link_summary(quote)
        assert summary["state"] == "active" and summary["recipient_hint"] == "a***@example.uz"
        assert summary["first_opened_at"] is not None
        doc_links.revoke_quote_links(quote, None)
        assert doc_links.client_link_summary(quote)["state"] == "revoked"


class TestSummaryFromFacts:
    """Состояние ссылки на карточке КП выводится из тех же фактов, что решают, откроется ли она у клиента."""

    def test_a_live_pre_transition_quote_is_active_with_the_expiry_date(self, quote):
        summary = doc_links.client_link_summary(quote)
        assert summary["state"] == "active"
        assert timezone.localtime(summary["expires_at"]).date() == quote.valid_until

    def test_a_pre_transition_quote_past_valid_until_is_expired_and_has_no_revoke(self, quote):
        Quote.objects.filter(pk=quote.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))
        quote.refresh_from_db()
        summary = doc_links.client_link_summary(quote)
        assert summary["state"] == "expired" and summary["expires_at"] is None

    def test_a_pre_transition_quote_with_a_lapsed_token_ttl_is_expired(self, quote):
        Quote.objects.filter(pk=quote.pk).update(public_token_expires_at=timezone.now() - datetime.timedelta(hours=1))
        quote.refresh_from_db()
        assert doc_links.client_link_summary(quote)["state"] == "expired"

    def test_a_pre_transition_quote_without_a_deadline_is_active_without_a_date(self, quote):
        Quote.objects.filter(pk=quote.pk).update(valid_until=None)
        quote.refresh_from_db()
        summary = doc_links.client_link_summary(quote)
        assert summary["state"] == "active" and summary["expires_at"] is None

    def test_a_revoked_old_page_is_revoked(self, quote):
        Quote.objects.filter(pk=quote.pk).update(public_token_revoked=True)
        quote.refresh_from_db()
        assert doc_links.client_link_summary(quote)["state"] == "revoked"

    def test_a_link_of_a_superseded_version_is_not_active(self, quote, minted):
        Quote.objects.create(deal=quote.deal, version=2, status=quote.status, frozen_at=timezone.now())
        assert doc_links.client_link_summary(quote)["state"] == "superseded"

    def test_an_old_page_of_a_superseded_version_is_not_active(self, quote):
        Quote.objects.create(deal=quote.deal, version=2, status=quote.status, frozen_at=timezone.now())
        assert doc_links.client_link_summary(quote)["state"] == "superseded"

    def test_an_expired_link_row_is_expired(self, quote, minted):
        link, _ = minted
        DocumentLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        assert doc_links.client_link_summary(quote)["state"] == "expired"


# ── старые ссылки страницы ERP ────────────────────────────────────────────────────────────────────────────────────


class TestLegacyRedirect:
    OLD = "/api/v1/public/quotes/{}/"

    def get(self, quote, **extra):
        from rest_framework.test import APIClient

        return APIClient().get(
            self.OLD.format(quote.public_access_token), HTTP_ACCEPT="text/html", SERVER_NAME="localhost", **extra
        )

    def test_old_link_in_a_browser_leads_to_the_cabinet_document(self, quote):
        response = self.get(quote)
        assert response.status_code == 302
        assert response["Location"].startswith("http://cabinet.localhost/d/")
        raw = response["Location"].rsplit("/", 1)[1]
        assert open_(raw).status_code == status.HTTP_200_OK

    def test_the_same_old_link_always_leads_to_the_same_document_link(self, quote):
        first = self.get(quote)["Location"]
        second = self.get(quote)["Location"]
        assert first == second and DocumentLink.objects.filter(quote=quote, legacy=True).count() == 1

    def test_old_link_has_the_quotes_expiry(self, quote):
        raw = self.get(quote)["Location"].rsplit("/", 1)[1]
        link = doc_links.find_link(raw)
        assert timezone.localtime(link.expires_at).date() == quote.valid_until + datetime.timedelta(days=30)

    def test_revoked_old_link_does_not_redirect(self, quote):
        Quote.objects.filter(pk=quote.pk).update(public_token_revoked=True)
        assert self.get(quote).status_code == 410

    def test_the_pdf_of_an_old_link_still_downloads(self, quote):
        from rest_framework.test import APIClient

        response = APIClient().get(self.OLD.format(quote.public_access_token) + "?export=pdf", SERVER_NAME="localhost")
        assert response.status_code == 200

    def test_old_link_of_a_superseded_quote_redirects_and_the_cabinet_names_the_reason(self, quote):
        Quote.objects.create(deal=quote.deal, version=2, status=quote.status, frozen_at=timezone.now())
        response = self.get(quote)
        assert response.status_code == 302
        raw = response["Location"].rsplit("/", 1)[1]
        opened = open_(raw)
        assert opened.status_code == status.HTTP_410_GONE and opened.json() == {"detail": "DOC_LINK_SUPERSEDED"}

    def test_switch_returns_the_erp_page(self, quote, settings):
        settings.PUBLIC_QUOTE_REDIRECT_TO_CABINET = False
        assert self.get(quote).status_code == 200 and not DocumentLink.objects.filter(legacy=True).exists()

    def test_old_link_of_a_quote_without_a_recipient_keeps_the_erp_page(self, quote):
        Deal.objects.filter(pk=quote.deal_id).update(contact=None)
        assert self.get(quote).status_code == 200


class TestValidUntilUsesCompanyDay:
    """«Действует до» — день компании (Asia/Tashkent), а не UTC: с 00:00 до 05:00 по Ташкенту вчерашний срок уже вышел."""

    def test_old_page_is_closed_after_midnight_in_tashkent(self, quote):
        import zoneinfo

        from crm.services.quotes import public_quote_gate

        tashkent_00_30 = datetime.datetime(2026, 11, 24, 0, 30, tzinfo=zoneinfo.ZoneInfo("Asia/Tashkent")).astimezone(
            datetime.timezone.utc
        )
        Quote.objects.filter(pk=quote.pk).update(valid_until=datetime.date(2026, 11, 23))
        quote.refresh_from_db()
        from unittest import mock

        with mock.patch("django.utils.timezone.now", return_value=tashkent_00_30):
            assert public_quote_gate(quote) is not None
