"""Тексты писем и PDF клиенту (owner 2026-11-24): без «ERP», «платформы» и внутренних id."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.core import mail
from django.test import override_settings
from portal.tests.conftest import LOCMEM_BACKEND

from notifications.emails import send_templated_email

pytestmark = pytest.mark.django_db

FOOTER = "Письмо отправлено автоматически. Ответить можно в кабинете или вашему менеджеру."


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND, PLATFORM_NAME="ERP")
@pytest.mark.parametrize(
    "template",
    ["portal_invitation", "portal_magic_link", "reset_password", "invite_member", "quote_accepted_contact"],
)
def test_stock_erp_name_never_reaches_the_client(template):
    from core.models.settings import SystemSetting

    SystemSetting.objects.update_or_create(pk=SystemSetting.load().pk, defaults={"platform_name": "ERP"})
    context = {
        "contact_name": "Азамат",
        "company_name": "Acme",
        "invite_url": "https://x.test/i",
        "login_url": "https://x.test/l",
        "login_code": "042917",
        "reset_url": "https://x.test/r",
        "setup_url": "https://x.test/s",
        "quote_number": "КП-1",
        "contract_number": "Д-1",
        "seller_name": "Acme",
    }
    mail.outbox = []
    send_templated_email(template, context, to=["a@example.test"], language="ru")
    message = mail.outbox[0]
    html = message.alternatives[0][0]
    for body in (message.body, html, message.subject):
        assert "ERP" not in body
        assert "платформ" not in body.lower()
    assert FOOTER in html


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
def test_company_name_is_shown_when_known_and_footer_is_plain():
    from core.models.settings import SystemSetting

    SystemSetting.objects.update_or_create(pk=SystemSetting.load().pk, defaults={"platform_name": "Acme Supply"})
    mail.outbox = []
    send_templated_email(
        "portal_magic_link",
        {"company_name": "Acme", "login_url": "https://x.test/l", "login_code": "1"},
        to=["a@example.test"],
        language="ru",
    )
    html = mail.outbox[0].alternatives[0][0]
    assert "© Acme Supply" in html and "мгновенно" not in html.lower()
    assert mail.outbox[0].body.rstrip().endswith("— Acme Supply")


def test_act_refs_name_the_project_not_the_internal_id():
    from crm.services.documents.rt_documents import _act_refs

    act = SimpleNamespace(deal_id=987654, deal=SimpleNamespace(number="ПР-2026-014"), contract_id=None)
    text = str(_act_refs(act, None))
    assert "ПР-2026-014" in text and "987654" not in text and "Сделка" not in text
