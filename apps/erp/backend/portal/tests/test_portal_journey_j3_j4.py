"""Тесты для Wave J3 (Уведомления под контролем) и J2-bank (Защита банковских реквизитов)."""

import pytest
from django.conf import settings
from parties.models import Company, CompanyType, Contact
from portal.models import NoticeChannel
from portal.services import notices
from portal.tests.conftest import PortalAPIClient, make_portal_session
from portal.views_notifications import get_contact_notification_settings

pytestmark = pytest.mark.django_db

PREFIX = "/api/portal/v1"


@pytest.fixture
def test_setup():
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    company = Company.objects.create(
        name="J3 Tech LLC",
        inn="123456789",
        legal_address="Tashkent, Chilanzar",
        bank_details="Old Bank Account 202080001000",
    )
    company.types.add(client_type)
    admin_contact = Contact.objects.create(
        company=company,
        name="Admin Contact",
        email="admin@j3.test",
        is_admin=True,
        can_act=True,
        telegram_user_id=111222333,
    )
    regular_contact = Contact.objects.create(
        company=company,
        name="Regular Contact",
        email="regular@j3.test",
        is_admin=False,
        can_act=True,
    )

    admin_session = make_portal_session(admin_contact, company, "magic_link")
    regular_session = make_portal_session(regular_contact, company, "magic_link")

    admin_client = PortalAPIClient()
    admin_client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = admin_session.raw_token
    admin_client.credentials(HTTP_X_PORTAL_SESSION=admin_session.raw_token)

    regular_client = PortalAPIClient()
    regular_client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = regular_session.raw_token
    regular_client.credentials(HTTP_X_PORTAL_SESSION=regular_session.raw_token)

    return {
        "company": company,
        "admin": admin_contact,
        "regular": regular_contact,
        "admin_client": admin_client,
        "regular_client": regular_client,
    }


def test_get_notification_settings_defaults(test_setup):
    client = test_setup["admin_client"]
    resp = client.get(f"{PREFIX}/notifications/settings")
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["telegram_connected"] is True
    groups = data["groups"]
    assert "documents" in groups
    assert "money" in groups
    assert "security" in groups
    assert groups["security"]["required"] is True
    assert groups["security"]["in_app"] is True
    assert groups["security"]["email"] is True
    assert groups["security"]["telegram"] is True


def test_patch_notification_settings(test_setup):
    client = test_setup["admin_client"]
    contact = test_setup["admin"]

    # Отключаем email для документов и денег
    payload = {
        "groups": {
            "documents": {"email": False, "telegram": True},
            "money": {"email": False, "telegram": False},
        }
    }
    resp = client.patch(f"{PREFIX}/notifications/settings", payload, format="json")
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["groups"]["documents"]["email"] is False
    assert data["groups"]["documents"]["telegram"] is True
    assert data["groups"]["money"]["email"] is False
    assert data["groups"]["money"]["telegram"] is False

    # Проверяем, что сохранилось в БД
    contact.refresh_from_db()
    settings = get_contact_notification_settings(contact)
    assert settings["documents"]["email"] is False
    assert settings["money"]["telegram"] is False
    # Безопасность не меняется
    assert settings["security"]["email"] is True


def test_choose_channel_respects_settings(test_setup):
    contact = test_setup["admin"]
    kind = notices.KINDS["invoice_issued"]  # group = money

    # По умолчанию — бот шлет в Telegram
    channel, reason = notices.choose_channel(
        kind, contact, bot_reaches=True, already_emailed=set(), document_contact_ids=[contact.pk]
    )
    assert channel == NoticeChannel.TELEGRAM

    # Отключаем Telegram для money
    contact.notification_settings = {"money": {"telegram": False, "email": True}}
    contact.save()
    channel, reason = notices.choose_channel(
        kind, contact, bot_reaches=True, already_emailed=set(), document_contact_ids=[contact.pk]
    )
    assert channel == NoticeChannel.EMAIL

    # Отключаем и email
    contact.notification_settings = {"money": {"telegram": False, "email": False}}
    contact.save()
    channel, reason = notices.choose_channel(
        kind, contact, bot_reaches=True, already_emailed=set(), document_contact_ids=[contact.pk]
    )
    assert channel == NoticeChannel.CABINET
    assert reason == "disabled_by_contact"


def test_bank_details_change_requires_admin(test_setup):
    regular_client = test_setup["regular_client"]
    admin_client = test_setup["admin_client"]
    company = test_setup["company"]

    # Обычный сотрудник пытается изменить банковские реквизиты -> 409 ADMIN_REQUIRED
    resp = regular_client.put(
        f"{PREFIX}/company",
        {"bank_details": "Hacked Account 9999999999"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json().get("detail") == "ADMIN_REQUIRED"

    # Админ меняет реквизиты -> 200 и уведомление создано
    resp = admin_client.put(
        f"{PREFIX}/company",
        {"bank_details": "New Official Account 202080009999"},
        format="json",
    )
    assert resp.status_code == 200
    company.refresh_from_db()
    assert company.bank_details == "New Official Account 202080009999"
