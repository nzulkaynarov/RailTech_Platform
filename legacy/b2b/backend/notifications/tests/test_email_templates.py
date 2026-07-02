"""Tests for the DB-backed email-template editor (Track 1).

Covers:
  * DB EmailTemplate row overrides the file template at render time.
  * A missing / inactive DB row falls back to the file template (backward compat).
  * preview action renders without sending.
  * test-send action delivers and writes an EmailLog.
  * IsPlatformAdmin gate — a non-admin gets 403.
"""

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from notifications.emails import _render_bodies, send_templated_email
from notifications.models import EmailLog, EmailTemplate

pytestmark = pytest.mark.django_db

_LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture(autouse=True)
def _locmem_channels(settings):
    """Force every email channel onto the in-memory backend so mail.outbox
    captures sends. EMAIL_CHANNELS bakes the backend at settings import, and the
    container sets EMAIL_BACKEND=console — overriding EMAIL_BACKEND alone is not
    enough, the channel config itself must point at locmem."""
    settings.EMAIL_CHANNELS = {name: {**cfg, "backend": _LOCMEM} for name, cfg in settings.EMAIL_CHANNELS.items()}


@pytest.fixture
def platform_admin():
    """SystemRole=ADMIN, no memberships → is_platform_admin == True."""
    role, _ = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin"})
    return CustomUser.objects.create_user(email="ops@railtech.uz", username="ops@railtech.uz", password="x", role=role)


@pytest.fixture
def regular_user():
    """A company member (not a platform admin)."""
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User"})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    user = CustomUser.objects.create_user(email="member@t.test", username="member@t.test", password="x")
    company = Company.objects.create(name="Buyer Co", inn="B1")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    return user


# --------------------------------------------------------------------------- #
# Render-layer: DB override vs file fallback                                   #
# --------------------------------------------------------------------------- #


def test_db_template_overrides_file():
    EmailTemplate.objects.create(
        key="setup_password",
        subject="DB SUBJECT {{ first_name }}",
        html_body="<p>DB HTML {{ first_name }}</p>",
        text_body="DB TEXT {{ first_name }} {{ setup_url }}",
        is_active=True,
    )
    subject, text_body, html_body = _render_bodies(
        "setup_password",
        {"first_name": "Алиса", "setup_url": "https://x?a=1&b=2"},
    )
    assert subject == "DB SUBJECT Алиса"
    assert "DB HTML Алиса" in html_body
    assert "DB TEXT Алиса" in text_body
    # Plain text keeps '&' unescaped (link-integrity behaviour preserved).
    assert "https://x?a=1&b=2" in text_body
    assert "&amp;" not in text_body


def test_missing_db_row_falls_back_to_file():
    assert not EmailTemplate.objects.filter(key="setup_password").exists()
    subject, text_body, html_body = _render_bodies(
        "setup_password",
        {"first_name": "Алиса", "setup_url": "https://app.example.com/setup?token=abc"},
    )
    # File template subject/body — not the DB sentinel strings.
    assert "DB SUBJECT" not in subject
    assert subject  # file template produced a non-empty subject
    assert text_body


def test_inactive_db_row_falls_back_to_file():
    EmailTemplate.objects.create(
        key="setup_password",
        subject="DB SUBJECT",
        html_body="<p>DB</p>",
        text_body="DB TEXT",
        is_active=False,  # disabled → ignored
    )
    subject, _text, _html = _render_bodies(
        "setup_password",
        {"first_name": "Алиса", "setup_url": "https://app.example.com/setup?token=abc"},
    )
    assert "DB SUBJECT" not in subject


def test_send_uses_db_template_and_logs():
    EmailTemplate.objects.create(
        key="setup_password",
        subject="Override subject",
        html_body="<p>hi {{ first_name }}</p>",
        text_body="hi {{ first_name }}",
        is_active=True,
    )
    mail.outbox = []
    log = send_templated_email(
        "setup_password",
        {"first_name": "Алиса", "setup_url": "https://x"},
        to=["r@example.com"],
    )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Override subject"
    assert log.status == EmailLog.STATUS_SENT


@pytest.mark.django_db
def test_emaillog_redacts_setup_reset_tokens():
    """SEC-02: the one-time credential params (?uid=&token=) in the SENT link must NOT be
    persisted to EmailLog (Unfold / DB-backup account-takeover vector). The delivered email
    keeps the real link; only the stored copy is redacted."""
    EmailTemplate.objects.create(
        key="setup_password",
        subject="Setup",
        html_body='<a href="{{ setup_url }}">set</a>',
        text_body="Open {{ setup_url }}",
        is_active=True,
    )
    mail.outbox = []
    url = "https://b2b.railtech.uz/setup-password?uid=MTI3&token=abc123-secretTOKEN&x=1"
    log = send_templated_email("setup_password", {"setup_url": url}, to=["r@example.com"])
    # Delivered email keeps the working link.
    assert "abc123-secretTOKEN" in mail.outbox[0].body
    # Persisted log has the token/uid redacted (non-secret params like x=1 survive).
    assert "abc123-secretTOKEN" not in log.body_text
    assert "abc123-secretTOKEN" not in log.body_html
    assert "MTI3" not in log.body_text
    assert "[REDACTED]" in log.body_text
    assert "x=1" in log.body_text


# --------------------------------------------------------------------------- #
# DRF: preview / test-send / permission gate                                  #
# --------------------------------------------------------------------------- #


def _make_template():
    return EmailTemplate.objects.create(
        key="kyc_verified",
        subject="KYC {{ company_name }}",
        html_body="<p>{{ company_name }} verified</p>",
        text_body="{{ company_name }} verified",
        is_active=True,
    )


def test_preview_renders_without_sending(platform_admin):
    template = _make_template()
    client = APIClient()
    client.force_authenticate(platform_admin)
    mail.outbox = []
    url = reverse("admin-email-template-preview", args=[template.pk])
    resp = client.post(url, {}, format="json")
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["subject"].startswith("KYC ")
    assert "verified" in data["text_body"]
    assert "verified" in data["html_body"]
    # Nothing sent, nothing logged.
    assert len(mail.outbox) == 0
    assert not EmailLog.objects.exists()


def test_preview_accepts_override_context(platform_admin):
    template = _make_template()
    client = APIClient()
    client.force_authenticate(platform_admin)
    url = reverse("admin-email-template-preview", args=[template.pk])
    resp = client.post(url, {"context": {"company_name": "ZZ Corp"}}, format="json")
    assert resp.status_code == 200
    assert "ZZ Corp" in resp.json()["subject"]


def test_test_send_delivers_and_writes_email_log(platform_admin):
    template = _make_template()
    client = APIClient()
    client.force_authenticate(platform_admin)
    mail.outbox = []
    url = reverse("admin-email-template-test-send", args=[template.pk])
    resp = client.post(url, {"to_email": "qa@example.com"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["status"] == EmailLog.STATUS_SENT
    assert body["email_log_id"] is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["qa@example.com"]
    log = EmailLog.objects.get(pk=body["email_log_id"])
    assert log.template == "kyc_verified"
    assert log.to_emails == ["qa@example.com"]


def test_crud_create_sets_updated_by(platform_admin):
    client = APIClient()
    client.force_authenticate(platform_admin)
    url = reverse("admin-email-template-list")
    resp = client.post(
        url,
        {
            "key": "quote_sent",
            "subject": "S",
            "html_body": "<p>h</p>",
            "text_body": "t",
            "is_active": True,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    created = EmailTemplate.objects.get(key="quote_sent")
    assert created.updated_by_id == platform_admin.id


def test_non_admin_gets_403(regular_user):
    template = _make_template()
    client = APIClient()
    client.force_authenticate(regular_user)
    # list
    assert client.get(reverse("admin-email-template-list")).status_code == 403
    # preview
    assert (
        client.post(reverse("admin-email-template-preview", args=[template.pk]), {}, format="json").status_code == 403
    )
    # test-send
    assert (
        client.post(
            reverse("admin-email-template-test-send", args=[template.pk]),
            {"to_email": "x@y.com"},
            format="json",
        ).status_code
        == 403
    )


def test_anonymous_gets_401(regular_user):
    template = _make_template()
    client = APIClient()
    assert client.get(reverse("admin-email-template-list")).status_code in (401, 403)
    assert client.post(reverse("admin-email-template-preview", args=[template.pk]), {}, format="json").status_code in (
        401,
        403,
    )
