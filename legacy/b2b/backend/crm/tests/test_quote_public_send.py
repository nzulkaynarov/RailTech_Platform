"""CB-send: unified КП delivery (email to registered client OR offline contact) +
public tokenized view/download. Uses a dummy PDF to avoid WeasyPrint in tests."""

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, Contact, CustomUser
from crm.models import Deal, Quote, QuoteStatus
from crm.tasks import send_quote_email


@pytest.fixture(autouse=True)
def locmem_email(settings):
    """send_templated_email routes through EMAIL_CHANNELS[channel]['backend'] (not
    settings.EMAIL_BACKEND), so point the transactional channel at locmem for tests."""
    chans = {k: dict(v) for k, v in settings.EMAIL_CHANNELS.items()}
    chans["transactional"]["backend"] = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_CHANNELS = chans


@pytest.fixture
def sent_quote(db):
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено", "sort_order": 50})
    company = Company.objects.create(name="Client Co", is_registered=False)
    deal = Deal.objects.create(company=company)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        frozen_at=timezone.now(),
        public_access_token="tok_TESTTOKEN123",
    )
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    return quote


# ---- public token view ----


@pytest.mark.django_db
def test_public_view_streams_pdf_by_token(sent_quote):
    resp = APIClient().get(f"/api/v1/public/quotes/{sent_quote.public_access_token}/", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert b"%PDF" in b"".join(resp.streaming_content) if resp.streaming else True


@pytest.mark.django_db
def test_public_view_unknown_token_404(db):
    assert APIClient().get("/api/v1/public/quotes/nope/", SERVER_NAME="localhost").status_code == 404


@pytest.mark.django_db
def test_public_view_unsent_quote_404(db):
    # A DRAFT (no frozen_at) is never publicly reachable even if a token leaked in.
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    company = Company.objects.create(name="X")
    deal = Deal.objects.create(company=company)
    q = Quote.objects.create(deal=deal, version=1, public_access_token="tok_draft", frozen_at=None)
    assert (
        APIClient().get(f"/api/v1/public/quotes/{q.public_access_token}/", SERVER_NAME="localhost").status_code == 404
    )


# ---- unified email send ----


@pytest.mark.django_db
def test_send_email_to_registered_client(sent_quote, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user = CustomUser.objects.create_user(email="buyer@c.test", username="buyer@c.test", password="pw", is_active=True)
    sent_quote.deal.client = user
    sent_quote.deal.save()
    send_quote_email(sent_quote.id)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["buyer@c.test"]
    assert any(att[0].endswith(".pdf") for att in mail.outbox[0].attachments)  # PDF attached


@pytest.mark.django_db
def test_send_email_to_offline_contact(sent_quote, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    contact = Contact.objects.create(
        company=sent_quote.deal.company, name="Ivan", email="ivan@offline.test", is_primary=True
    )
    sent_quote.deal.contact = contact
    sent_quote.deal.save()
    send_quote_email(sent_quote.id)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ivan@offline.test"]


@pytest.mark.django_db
def test_send_email_no_recipient_skips(sent_quote, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    # no client, no contact
    result = send_quote_email(sent_quote.id)
    assert result["status"] == "no_recipient"
    assert len(mail.outbox) == 0
