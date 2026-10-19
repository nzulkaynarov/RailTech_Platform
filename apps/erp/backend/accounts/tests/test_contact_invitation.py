"""Tests for Contact Portal Invitations (M2-ERP-02).

DoD:
1. «Пригласить» на контакте (e-mail и/или Telegram) через POST /api/v1/accounts/contacts/{id}/invite/.
2. Письмо рендерится в обеих локалях (ru, en), создаётся запись в журнале EmailLog.
3. Предпочитаемый канал контакта (email, telegram, both).
4. Регистрация с улицы отключена: неизвестный email или telegram_user_id не создаёт аккаунтов.
5. Защита правами роли (deal.manage).
"""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from portal.models import MagicLinkToken
from portal.services.tokens import hash_token
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, Contact, CustomUser, WorkspaceRole
from notifications.models import EmailLog

LOCMEM_CHANNELS = {
    ch: {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "test@example.com",
    }
    for ch in ("transactional", "marketing", "system")
}


@pytest.fixture
def seller_company(db):
    company = Company.objects.create(name="RailTech Seller", is_registered=True)
    seller_type, _ = CompanyType.objects.get_or_create(code="SELLER", defaults={"name": "Seller"})
    company.types.add(seller_type)
    return company


@pytest.fixture
def client_company(db):
    return Company.objects.create(name="Tashkent Metro LLC", is_registered=False)


@pytest.fixture
def seller_user(db, seller_company):
    user = CustomUser.objects.create_user(
        username="seller_rep@example.com",
        email="seller_rep@example.com",
        password="testpassword123",
        is_staff=True,
    )
    ws_role = WorkspaceRole.objects.first() or WorkspaceRole.objects.create(name="Owner", code="OWNER")
    head_role = CompanyRole.objects.create(
        company=seller_company,
        code="HEAD",
        name="Head",
        permissions=["deal.manage"],
    )
    member = CompanyMember.objects.create(
        user=user,
        company=seller_company,
        role=ws_role,
        can_sell=True,
        is_active=True,
    )
    member.company_roles.add(head_role)
    return user


@pytest.fixture
def viewer_user(db, seller_company):
    user = CustomUser.objects.create_user(
        username="viewer@example.com",
        email="viewer@example.com",
        password="testpassword123",
        is_staff=True,
    )
    ws_role = WorkspaceRole.objects.first() or WorkspaceRole.objects.create(name="Owner", code="OWNER")
    viewer_role = CompanyRole.objects.create(
        company=seller_company,
        code="VIEWER",
        name="Viewer",
        permissions=[],
    )
    member = CompanyMember.objects.create(
        user=user,
        company=seller_company,
        role=ws_role,
        can_sell=True,
        is_active=True,
    )
    member.company_roles.add(viewer_role)
    return user


@pytest.fixture
def client_contact(db, client_company, seller_user):
    return Contact.objects.create(
        company=client_company,
        name="Азиз Каримов",
        email="aziz.karimov@tashkentmetro.uz",
        phone="+998901234567",
        position="Главный инженер",
        is_primary=True,
        created_by=seller_user,
        preferred_channel="email",
        language="ru",
        can_act=True,
    )


@pytest.fixture(autouse=True)
def configure_email_and_portal_settings(settings, seller_company):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    settings.CABINET_URL = "http://cabinet.localhost"
    settings.TELEGRAM_BOT_USERNAME = "railtech_test_bot"
    settings.OWN_COMPANY_ID = seller_company.id


@pytest.mark.django_db
class TestContactInvitation:
    def test_invite_contact_via_email(self, client_contact, seller_user):
        """Успешное приглашение по email создает токен, отправляет письмо и пишет в EmailLog."""
        mail.outbox.clear()
        client = APIClient()
        client.force_authenticate(user=seller_user)

        response = client.post(f"/api/v1/accounts/contacts/{client_contact.id}/invite/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["ok"] is True
        assert data["email_sent"] is True
        assert data["channel"] == "email"
        # FIX-14: сотруднику рабочая ссылка входа клиента не отдаётся — только факт отправки и канал
        assert set(data) == {"ok", "contact_id", "channel", "email_sent", "invited_at"}
        assert "/auth/magic" not in response.content.decode()

        # Проверяем, что дата приглашения зафиксирована
        client_contact.refresh_from_db()
        assert client_contact.invited_at is not None

        # Проверяем, что письмо отправлено
        assert len(mail.outbox) == 1
        sent_email = mail.outbox[0]
        assert "aziz.karimov@tashkentmetro.uz" in sent_email.to
        assert "Tashkent Metro LLC" in sent_email.subject

        # Письмо клиенту содержит рабочую ссылку, база и EmailLog — нет
        # FIX-21: токен — во фрагменте ссылки (`#token=`), в пути и query его нет
        assert "http://cabinet.localhost/auth/magic#token=" in sent_email.body
        raw_token = re.search(r"/auth/magic#token=([\w-]+)", sent_email.body).group(1)
        assert f"/auth/magic/{raw_token}" not in sent_email.body and f"token={raw_token}&" not in sent_email.body
        stored = MagicLinkToken.objects.get(contact=client_contact)
        assert stored.token_hash == hash_token(raw_token) != raw_token
        assert stored.purpose == MagicLinkToken.PURPOSE_INVITE
        assert not EmailLog.objects.filter(body_text__contains=raw_token).exists()
        assert not EmailLog.objects.filter(body_html__contains=raw_token).exists()

        # Проверяем запись в EmailLog
        log = EmailLog.objects.filter(
            to_emails__contains=["aziz.karimov@tashkentmetro.uz"],
            template="portal_invitation",
        ).first()
        assert log is not None
        assert log.status == EmailLog.STATUS_SENT

    def test_bilingual_email_rendering(self, client_contact, seller_user):
        """Письмо рендерится в обеих локалях (ru и en)."""
        mail.outbox.clear()
        client = APIClient()
        client.force_authenticate(user=seller_user)

        # 1. Запрос на английском (language='en')
        resp_en = client.post(
            f"/api/v1/accounts/contacts/{client_contact.id}/invite/",
            {"language": "en"},
            format="json",
        )
        assert resp_en.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        email_en = mail.outbox[0]
        assert "Invitation to «Tashkent Metro LLC»" in email_en.subject or "Tashkent Metro LLC" in email_en.subject

        # 2. Запрос на русском (language='ru')
        mail.outbox.clear()
        resp_ru = client.post(
            f"/api/v1/accounts/contacts/{client_contact.id}/invite/",
            {"language": "ru"},
            format="json",
        )
        assert resp_ru.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        email_ru = mail.outbox[0]
        assert "Приглашение в личный кабинет «Tashkent Metro LLC»" in email_ru.subject

    def test_invite_contact_missing_email(self, db, client_company, seller_user):
        """Приглашение контакта без email по email-каналу возвращает 400 CONTACT_EMAIL_REQUIRED."""
        contact = Contact.objects.create(
            company=client_company,
            name="Контакт без email",
            email="",
            phone="+998909998877",
            created_by=seller_user,
            preferred_channel="email",
        )

        client = APIClient()
        client.force_authenticate(user=seller_user)

        response = client.post(
            f"/api/v1/accounts/contacts/{contact.id}/invite/",
            {"channel": "email"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "CONTACT_EMAIL_REQUIRED"

    def test_invite_contact_via_telegram(self, db, client_company, seller_user):
        """Приглашение по каналу telegram возвращает telegram_url и не требует email."""
        contact = Contact.objects.create(
            company=client_company,
            name="Telegram контакт",
            email="",
            phone="+998901112233",
            telegram_username="tg_client",
            created_by=seller_user,
            preferred_channel="telegram",
        )

        client = APIClient()
        client.force_authenticate(user=seller_user)

        response = client.post(
            f"/api/v1/accounts/contacts/{contact.id}/invite/",
            {"channel": "telegram"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["channel"] == "telegram"
        assert data["email_sent"] is False
        assert set(data) == {"ok", "contact_id", "channel", "email_sent", "invited_at"}
        # Telegram-вход идёт по подписанному initData, ссылка-токен не нужна и не создаётся
        assert not MagicLinkToken.objects.filter(contact=contact).exists()

    def test_invite_contact_of_archived_company_is_refused(self, client_contact, client_company, seller_user):
        """FIX-14: архивной компании приглашение не уходит — ни письма, ни токена."""
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])
        mail.outbox.clear()
        client = APIClient()
        client.force_authenticate(user=seller_user)

        response = client.post(f"/api/v1/accounts/contacts/{client_contact.id}/invite/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "COMPANY_ARCHIVED"
        assert mail.outbox == []
        assert not MagicLinkToken.objects.filter(contact=client_contact).exists()

    def test_reinvite_revokes_only_previous_invitations(self, client_contact, seller_user):
        """FIX-14 (P-10): повторное приглашение гасит прежнее приглашение, но не ссылку входа, запрошенную клиентом."""
        client = APIClient()
        client.force_authenticate(user=seller_user)
        login = MagicLinkToken.objects.create(
            token_hash=hash_token("client-requested-login"),
            contact=client_contact,
            purpose=MagicLinkToken.PURPOSE_LOGIN,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        client.post(f"/api/v1/accounts/contacts/{client_contact.id}/invite/")
        client.post(f"/api/v1/accounts/contacts/{client_contact.id}/invite/")

        login.refresh_from_db()
        assert login.used_at is None
        invites = MagicLinkToken.objects.filter(contact=client_contact, purpose=MagicLinkToken.PURPOSE_INVITE)
        assert invites.count() == 2
        assert invites.filter(used_at__isnull=True).count() == 1

    def test_permission_denied_without_deal_manage(self, client_contact, viewer_user):
        """Сотрудник без права deal.manage получает 403 ROLE_NOT_PERMITTED."""
        client = APIClient()
        client.force_authenticate(user=viewer_user)

        response = client.post(f"/api/v1/accounts/contacts/{client_contact.id}/invite/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "ROLE_NOT_PERMITTED"

    def test_registration_from_street_disabled(self, db):
        """Регистрация с улицы отключена: чужой email не создаёт контакт."""
        client = APIClient()

        # 1. Запрос magic-link на неизвестный email не создаёт контактов
        count_before = Contact.objects.count()
        resp = client.post(
            "/api/portal/v1/auth/magic-link",
            {"email": "stranger@unknown.com"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="invite-test-magic-link",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert Contact.objects.count() == count_before
        assert MagicLinkToken.objects.filter(contact__email="stranger@unknown.com").count() == 0

        # 2. Попытка входа через Telegram неизвестного пользователя
        resp_tg = client.post(
            "/api/portal/v1/auth/telegram",
            {
                "id": 999999999,
                "first_name": "Stranger",
                "auth_date": 1234567890,
                "hash": "fake",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="invite-test-telegram",
        )
        assert resp_tg.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
        assert Contact.objects.filter(telegram_user_id=999999999).count() == 0
