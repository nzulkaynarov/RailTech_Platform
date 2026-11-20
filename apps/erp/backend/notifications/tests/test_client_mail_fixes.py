"""СЦ-4: в письме клиенту нет чужих данных и одноразовых секретов в теме.

Случай прода 2026-11-19: код принятия КП стоял в теме письма (и письмо ушло в спам), в подвале — `support@example.com`
(адрес поддержки не задан, действовала заглушка), а письмо «Принято» не говорило, что дальше и у кого.
"""

import pytest
from django.core import mail

from core.models.settings import SystemSetting
from notifications.emails import real_support_email, send_templated_email

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def _send(template: str, context: dict, to: str = "client@example.uz"):
    send_templated_email(template, context, to=[to], language="ru")
    return mail.outbox[-1]


def test_acceptance_code_is_in_the_body_not_in_the_subject():
    message = _send(
        "quote_acceptance_code",
        {"quote_number": "RFQ-1126-01", "seller_name": "ООО «Продавец»", "code": "241742", "expires_minutes": 15},
    )
    assert message.subject == "Код для принятия КП RFQ-1126-01"
    assert "241742" not in message.subject
    assert "241742" in message.body and "241742" in message.alternatives[0][0]


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("support@example.com", ""),
        ("", ""),
        (None, ""),
        (" Help@Example.ORG ", ""),
        ("support@railtech.uz", "support@railtech.uz"),
    ],
)
def test_placeholder_support_address_is_not_a_real_one(value, shown):
    assert real_support_email(value) == shown


def test_footer_has_no_support_line_until_a_real_address_is_set():
    settings_row = SystemSetting.load()
    settings_row.support_email = "support@example.com"
    settings_row.save(update_fields=["support_email"])
    html = _send("quote_sent", {"seller_name": "S", "quote_number": "1"}).alternatives[0][0]
    assert "example.com" not in html and "Возникли вопросы" not in html

    settings_row.support_email = "support@railtech.uz"
    settings_row.save(update_fields=["support_email"])
    html = _send("quote_sent", {"seller_name": "S", "quote_number": "1"}).alternatives[0][0]
    assert "mailto:support@railtech.uz" in html


def test_accepted_letter_names_the_next_step_owner_and_links_back():
    message = _send(
        "quote_accepted_contact",
        {
            "quote_number": "RFQ-1126-01",
            "contract_number": "ДГ-2026/001",
            "seller_name": "ООО «Продавец»",
            "manager_name": "Алишер Каримов",
            "manager_email": "alisher@railtech.uz",
            "public_link": "https://erp.example.uz/api/v1/public/quotes/tok/",
        },
    )
    html = message.alternatives[0][0]
    for text in (message.body, html):
        assert "Ваш менеджер — Алишер Каримов" in text
        assert "alisher@railtech.uz" in text
        assert "https://erp.example.uz/api/v1/public/quotes/tok/" in text


def test_placeholder_in_the_database_does_not_hide_the_real_address_from_the_environment(settings):
    """СЦ-3: в базе заглушка (её посеяли до настройки), в окружении — настоящий адрес: в письме — он."""
    settings.SUPPORT_EMAIL = "help@rt.uz"
    settings_row = SystemSetting.load()
    settings_row.support_email = "support@example.com"
    settings_row.save(update_fields=["support_email"])
    html = _send("quote_sent", {"seller_name": "S", "quote_number": "1"}).alternatives[0][0]
    assert "mailto:help@rt.uz" in html

    settings_row.support_email = "support@railtech.uz"
    settings_row.save(update_fields=["support_email"])
    html = _send("quote_sent", {"seller_name": "S", "quote_number": "1"}).alternatives[0][0]
    assert "mailto:support@railtech.uz" in html, "настоящий адрес в базе главнее окружения"
