"""Wave A — public КП page: content negotiation, «viewed» beacon, offline email-code acceptance.

Runs with --nomigrations (pyproject addopts), so every lookup code the flow touches is seeded
explicitly here (the data migrations that normally create them are skipped).

Security coverage (adversarial) for the email-code accept flow:
  * wrong code / expired code / reused code / attempt cap
  * enumeration-neutral request-code response (recipient exists vs not → identical body)
  * IDOR: a code minted for quote A cannot accept quote B
  * throttle on the code-request endpoint
"""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, Contact, CustomUser
from crm.models import (
    ActivityLog,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Quote,
    QuoteAcceptanceCode,
    QuoteItem,
    QuoteStatus,
)
from master_data.models import Currency
from notifications.models import Notification, NotificationType

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def locmem_email(settings):
    chans = {k: dict(v) for k, v in settings.EMAIL_CHANNELS.items()}
    chans["transactional"]["backend"] = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_CHANNELS = chans


@pytest.fixture
def lookups(db):
    for code in ["RFQ_OPEN", "SOURCING", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "READY_TO_SEND", "SENT", "APPROVED", "REJECTED", "EXPIRED"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "PENDING_CLIENT", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["INFO", "SUCCESS", "WARNING"]:
        NotificationType.objects.get_or_create(code=code, defaults={"name": code})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Sum", "symbol": "сум", "sort_order": 10})


_INN_SEQ = [300000000]


def _next_inn():
    _INN_SEQ[0] += 1
    return str(_INN_SEQ[0])


def _make_sent_quote(*, token, contact_email="buyer@acme.uz", stage="QUOTE_SENT", with_item=True):
    seller_user = CustomUser.objects.create_user(
        email=f"seller_{token}@rail.uz", username=f"seller_{token}", password="pw", is_active=True, first_name="Aziz"
    )
    seller = Company.objects.create(name="RailTech Seller", inn=_next_inn())
    client_company = Company.objects.create(name="ACME Buyer", inn=_next_inn(), is_registered=False)
    contact = None
    if contact_email is not None:
        contact = Contact.objects.create(company=client_company, name="Buyer Person", email=contact_email)
    deal = Deal.objects.create(
        company=client_company, contact=contact, stage=DealStage.objects.get(code=stage), title="Deal WaveA"
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        number=f"КП-2026-{token[-4:]}",
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller,
        prepared_by=seller_user,
        quote_currency=Currency.objects.get(code="UZS"),
        frozen_at=timezone.now(),
        public_access_token=token,
    )
    if with_item:
        QuoteItem.objects.create(
            quote=quote,
            imported_raw_name="Подшипник буксовый",
            quantity=10,
            frozen_base_price=Decimal("1000000.00"),
            margin_percent=Decimal("25.00"),
            frozen_currency=Currency.objects.get(code="UZS"),
        )
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    quote.refresh_from_db()
    return quote, seller_user


def _url(quote, suffix=""):
    return f"/api/v1/public/quotes/{quote.public_access_token}/{suffix}"


def _extract_code(message):
    return re.search(r"\b\d{6}\b", message.body).group(0)


# ── 1. Content negotiation ────────────────────────────────────────────────


@pytest.mark.django_db
def test_page_js_served_same_origin(db):
    """The page JS is served by Django (CSP script-src 'self'), tokenless, correct content-type."""
    resp = APIClient().get("/api/v1/public/quote-page.js", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/javascript")
    assert b"viewed/" in resp.content  # the beacon path is wired in the served script


@pytest.mark.django_db
def test_browser_gets_html_page(lookups):
    quote, _ = _make_sent_quote(token="tok_htmlpage_1")
    resp = APIClient().get(_url(quote), HTTP_ACCEPT="text/html", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/html")
    body = resp.content.decode()
    assert "Принять предложение" in body
    assert quote.number in body
    assert "Коммерческое предложение" in body


@pytest.mark.django_db
def test_download_still_returns_pdf(lookups):
    quote, _ = _make_sent_quote(token="tok_pdf_1")
    # ?export=pdf → PDF even from a browser Accept.
    resp = APIClient().get(_url(quote) + "?export=pdf", HTTP_ACCEPT="text/html", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert b"%PDF" in b"".join(resp.streaming_content)


@pytest.mark.django_db
def test_expired_link_browser_gets_410_html_page(lookups):
    quote, _ = _make_sent_quote(token="tok_exp_1")
    quote.valid_until = (timezone.now() - timedelta(days=1)).date()
    quote.save(update_fields=["valid_until"])
    resp = APIClient().get(_url(quote), HTTP_ACCEPT="text/html", SERVER_NAME="localhost")
    assert resp.status_code == 410
    assert resp["Content-Type"].startswith("text/html")
    assert "Срок ссылки истёк" in resp.content.decode()


@pytest.mark.django_db
def test_page_never_leaks_cost_or_margin(lookups):
    """CONFIDENTIALITY: the public page renders the client projection only — no cost/margin words,
    no landed_cost, no margin percentage."""
    quote, _ = _make_sent_quote(token="tok_leak_1")
    body = APIClient().get(_url(quote), HTTP_ACCEPT="text/html", SERVER_NAME="localhost").content.decode()
    # Internal cost/margin fields must never appear in the client projection. ("margin"/"25%" are
    # avoided as literals — CSS `margin:` and НДС would false-match; assert the domain terms.)
    for forbidden in ["Себестоимость", "Маржа", "landed_cost", "margin_percent", "frozen_base_price"]:
        assert forbidden not in body, forbidden


# ── 2. «Viewed» beacon (no false positives on the bare GET) ────────────────


@pytest.mark.django_db
def test_bare_get_does_not_fire_view_event(lookups):
    quote, _ = _make_sent_quote(token="tok_view_noget")
    APIClient().get(_url(quote), HTTP_ACCEPT="text/html", SERVER_NAME="localhost")
    quote.refresh_from_db()
    assert quote.first_viewed_at is None
    assert not ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.viewed").exists()


@pytest.mark.django_db
def test_beacon_records_view_and_notifies_seller(lookups):
    quote, seller_user = _make_sent_quote(token="tok_view_beacon")
    resp = APIClient().post(_url(quote, "viewed/"), SERVER_NAME="localhost")
    assert resp.status_code == 204
    quote.refresh_from_db()
    assert quote.first_viewed_at is not None
    assert ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.viewed").count() == 1
    assert Notification.objects.filter(user=seller_user, title="КП просмотрено клиентом").exists()


@pytest.mark.django_db
def test_beacon_dedup_second_open_is_noop(lookups):
    quote, _ = _make_sent_quote(token="tok_view_dedup")
    client = APIClient()
    client.post(_url(quote, "viewed/"), SERVER_NAME="localhost")
    quote.refresh_from_db()
    first_ts = quote.first_viewed_at
    client.post(_url(quote, "viewed/"), SERVER_NAME="localhost")
    quote.refresh_from_db()
    assert quote.first_viewed_at == first_ts
    assert ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.viewed").count() == 1


# ── 3. Offline email-code acceptance ───────────────────────────────────────


@pytest.mark.django_db
def test_request_code_creates_code_and_emails(lookups):
    quote, _ = _make_sent_quote(token="tok_reqcode")
    resp = APIClient().post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert QuoteAcceptanceCode.objects.filter(quote=quote, consumed_at__isnull=True).count() == 1
    assert len(mail.outbox) == 1
    assert "buyer@acme.uz" in mail.outbox[0].to


@pytest.mark.django_db
def test_request_code_enumeration_neutral(lookups):
    """No recipient on the deal → SAME neutral 200 body, no code, no email (no enumeration leak)."""
    with_recipient, _ = _make_sent_quote(token="tok_enum_yes", contact_email="x@acme.uz")
    without_recipient, _ = _make_sent_quote(token="tok_enum_no", contact_email=None)
    r1 = APIClient().post(_url(with_recipient, "request-code/"), SERVER_NAME="localhost")
    r2 = APIClient().post(_url(without_recipient, "request-code/"), SERVER_NAME="localhost")
    assert r1.status_code == r2.status_code == 200
    assert r1.data == r2.data
    assert QuoteAcceptanceCode.objects.filter(quote=without_recipient).count() == 0


@pytest.mark.django_db
def test_full_accept_flow_materializes_contract(lookups):
    quote, seller_user = _make_sent_quote(token="tok_accept_ok")
    client = APIClient()
    client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    code = _extract_code(mail.outbox[0])

    resp = client.post(_url(quote, "accept/"), {"code": code}, format="json", SERVER_NAME="localhost")
    assert resp.status_code == 200, resp.data
    assert resp.data["detail"] == "ACCEPTED"

    quote.refresh_from_db()
    assert quote.status.code == "APPROVED"
    assert quote.approved_by is None  # offline contact — no User acceptor
    assert quote.deal.stage.code == "CONTRACT_SIGNED"
    assert Contract.objects.filter(deal=quote.deal, quote=quote).exists()

    # Timeline event records the contact acceptance channel + email (approved_by=None → user NULL).
    log = ActivityLog.objects.get(entity_id=quote.id, event_code="quote.accepted")
    assert log.user is None
    assert log.event_params.get("channel") == "offline_contact"
    assert log.event_params.get("contact_email") == "buyer@acme.uz"
    # Seller notified + next-step email to the contact.
    assert Notification.objects.filter(user=seller_user, title="КП одобрено клиентом").exists()
    assert any("buyer@acme.uz" in m.to for m in mail.outbox[1:])

    # Code is single-use → consumed.
    assert QuoteAcceptanceCode.objects.get(quote=quote).consumed_at is not None


@pytest.mark.django_db
def test_wrong_code_rejected_and_quote_untouched(lookups):
    quote, _ = _make_sent_quote(token="tok_wrong")
    client = APIClient()
    client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    resp = client.post(_url(quote, "accept/"), {"code": "000000"}, format="json", SERVER_NAME="localhost")
    # (guard against the 1-in-a-million coincidence that the real code is 000000)
    real = _extract_code(mail.outbox[0])
    if real != "000000":
        assert resp.status_code == 400
        assert resp.data["detail"] == "INVALID_CODE"
        quote.refresh_from_db()
        assert quote.status.code == "SENT"
        assert QuoteAcceptanceCode.objects.get(quote=quote).attempts == 1


@pytest.mark.django_db
def test_attempt_cap_locks_the_code(lookups):
    quote, _ = _make_sent_quote(token="tok_cap")
    client = APIClient()
    client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    # 5 wrong attempts → INVALID_CODE; the 6th → TOO_MANY_ATTEMPTS regardless of the value.
    for _ in range(5):
        r = client.post(_url(quote, "accept/"), {"code": "111111"}, format="json", SERVER_NAME="localhost")
        assert r.data["detail"] == "INVALID_CODE"
    blocked = client.post(_url(quote, "accept/"), {"code": "111111"}, format="json", SERVER_NAME="localhost")
    assert blocked.data["detail"] == "TOO_MANY_ATTEMPTS"


@pytest.mark.django_db
def test_expired_code_rejected(lookups):
    quote, _ = _make_sent_quote(token="tok_codeexp")
    client = APIClient()
    client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    code = _extract_code(mail.outbox[0])
    QuoteAcceptanceCode.objects.filter(quote=quote).update(expires_at=timezone.now() - timedelta(minutes=1))
    resp = client.post(_url(quote, "accept/"), {"code": code}, format="json", SERVER_NAME="localhost")
    assert resp.data["detail"] == "CODE_EXPIRED"


@pytest.mark.django_db
def test_reused_code_rejected(lookups):
    quote, _ = _make_sent_quote(token="tok_reuse")
    client = APIClient()
    client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    code = _extract_code(mail.outbox[0])
    ok = client.post(_url(quote, "accept/"), {"code": code}, format="json", SERVER_NAME="localhost")
    assert ok.status_code == 200
    again = client.post(_url(quote, "accept/"), {"code": code}, format="json", SERVER_NAME="localhost")
    assert again.data["detail"] == "NO_ACTIVE_CODE"


@pytest.mark.django_db
def test_idor_code_for_quote_a_cannot_accept_quote_b(lookups):
    quote_a, _ = _make_sent_quote(token="tok_idor_a")
    quote_b, _ = _make_sent_quote(token="tok_idor_b")
    client = APIClient()
    client.post(_url(quote_a, "request-code/"), SERVER_NAME="localhost")
    code_a = _extract_code(mail.outbox[0])
    # Use A's code against B's token → B has no active code → rejected; B stays SENT.
    resp = client.post(_url(quote_b, "accept/"), {"code": code_a}, format="json", SERVER_NAME="localhost")
    assert resp.data["detail"] == "NO_ACTIVE_CODE"
    quote_b.refresh_from_db()
    assert quote_b.status.code == "SENT"


@override_settings(CACHES=LOCMEM)
@pytest.mark.django_db
def test_request_code_throttled(lookups):
    """public_quote_code = 5/hour per IP → the 6th request-code is rejected (email-bomb shield)."""
    quote, _ = _make_sent_quote(token="tok_throttle")
    client = APIClient()
    for _ in range(5):
        client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    blocked = client.post(_url(quote, "request-code/"), SERVER_NAME="localhost")
    assert blocked.status_code == 429


# ── 4. Reject with reason ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_reject_with_reason(lookups):
    quote, seller_user = _make_sent_quote(token="tok_reject")
    resp = APIClient().post(
        _url(quote, "reject/"), {"reason": "Слишком дорого"}, format="json", SERVER_NAME="localhost"
    )
    assert resp.status_code == 200
    quote.refresh_from_db()
    assert quote.status.code == "REJECTED"
    assert quote.deal.stage.code == "CALCULATING"
    assert ActivityLog.objects.filter(entity_id=quote.id, event_code="quote.rejected").exists()
    assert Notification.objects.filter(user=seller_user, title="КП отклонено клиентом").exists()


@pytest.mark.django_db
def test_reject_without_reason_400(lookups):
    quote, _ = _make_sent_quote(token="tok_reject_noreason")
    resp = APIClient().post(_url(quote, "reject/"), {"reason": "  "}, format="json", SERVER_NAME="localhost")
    assert resp.status_code == 400
    assert resp.data["detail"] == "REASON_REQUIRED"
    quote.refresh_from_db()
    assert quote.status.code == "SENT"
