"""K0: в кабинет входят только компании с типом CLIENT (решение владельца 2026-11-01, до волны K1).

Поставщик (SUPPLIER), производитель и своя компания (тип SUPPLIER) не получают ни письма со ссылкой, ни сессии по
Telegram, ни приглашения; сессия, у компании которой сняли CLIENT, гаснет на следующем же запросе.
"""

import pytest
from django.core import mail
from parties.models import Company, CompanyType, Contact
from portal.models import MagicLinkToken, PortalSession
from portal.services.access import company_has_cabinet_access
from portal.services.invitation import invite_contact, invite_team_member
from portal.tests.conftest import LOCMEM_BACKEND, make_portal_session, make_telegram_init_data
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

MAGIC_LINK_URL = "/api/portal/v1/auth/magic-link"
MAGIC_EXCHANGE_URL = "/api/portal/v1/auth/magic"
TELEGRAM_URL = "/api/portal/v1/auth/telegram"
ME = "/api/portal/v1/me"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem_mail(settings, inline_magic_link_task):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


def _type(code):
    return CompanyType.objects.get_or_create(code=code, defaults={"name": code})[0]


def _company(name, inn, *codes):
    """Компания с заданными типами; CLIENT, которого нет в `codes`, снимается (типов-то хоть один остаётся)."""
    company = Company.objects.create(name=name, inn=inn)
    for code in codes:
        company.types.add(_type(code))
    if "CLIENT" not in codes and company.types.exists():
        company.types.remove(_type("CLIENT"))
    return company


def _strip_client(company):
    """Снять с компании CLIENT, оставив другой тип (иначе сигнал вернёт CLIENT как «тип по умолчанию»)."""
    company.types.add(_type("SUPPLIER"))
    company.types.remove(_type("CLIENT"))
    assert not company.types.filter(code="CLIENT").exists()


def _contact(company, email, telegram_user_id=None):
    return Contact.objects.create(
        company=company, name="Контакт " + company.name, email=email, telegram_user_id=telegram_user_id, can_act=True
    )


@pytest.fixture
def own(seller_company, settings):
    """Своя компания (владелец ERP) с лишним CLIENT (остался с времён сигнала «продавец тоже покупает», до миграции
    accounts/0013); `OWN_COMPANY_ID` — явный выбор."""
    seller_company.types.add(_type("CLIENT"))
    settings.OWN_COMPANY_ID = seller_company.pk
    return seller_company


@pytest.fixture
def supplier_contact(db):
    company = _company("OOO Supplier", "111000111", "SUPPLIER")
    return _contact(company, "buyer@supplier.example.uz", telegram_user_id=700100200)


class TestRule:
    def test_only_client_type_is_admitted(self, client_company):
        assert company_has_cabinet_access(client_company.pk) is True
        assert company_has_cabinet_access(_company("S", "1", "SUPPLIER").pk) is False
        assert company_has_cabinet_access(_company("M", "2", "MANUFACTURER").pk) is False
        assert company_has_cabinet_access(None) is False

    def test_own_company_is_not_admitted_even_with_client_type(self, own):
        """Если у своей компании остался CLIENT, кабинет ей всё равно закрыт."""
        assert own.types.filter(code="CLIENT").exists()
        assert company_has_cabinet_access(own.pk) is False

    def test_client_and_supplier_is_admitted(self):
        assert company_has_cabinet_access(_company("Both", "4", "CLIENT", "SUPPLIER").pk) is True

    def test_archived_client_is_not_admitted(self, client_company):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])
        assert company_has_cabinet_access(client_company.pk) is False


class TestMagicLink:
    def test_supplier_gets_no_mail_and_same_answer(self, supplier_contact, client_contact, anon_portal_client):
        known = anon_portal_client.post(MAGIC_LINK_URL, {"email": client_contact.email}, format="json")
        mail.outbox.clear()
        supplier = anon_portal_client.post(MAGIC_LINK_URL, {"email": supplier_contact.email}, format="json")
        unknown = anon_portal_client.post(MAGIC_LINK_URL, {"email": "nobody@example.com"}, format="json")

        assert known.status_code == supplier.status_code == unknown.status_code == status.HTTP_200_OK
        strip = lambda r: {k: v for k, v in r.data.items() if k != "email"}  # noqa: E731
        assert strip(supplier) == strip(known) == strip(unknown)
        assert mail.outbox == []
        assert not MagicLinkToken.objects.filter(contact=supplier_contact).exists()

    def test_own_company_contact_gets_no_mail(self, own, anon_portal_client):
        contact = _contact(own, "boss@railtech.example.uz")

        response = anon_portal_client.post(MAGIC_LINK_URL, {"email": contact.email}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert mail.outbox == []
        assert not MagicLinkToken.objects.filter(contact=contact).exists()

    def test_company_with_client_and_supplier_gets_the_link(self, anon_portal_client):
        contact = _contact(_company("Both", "222000222", "CLIENT", "SUPPLIER"), "both@example.uz")

        response = anon_portal_client.post(MAGIC_LINK_URL, {"email": contact.email}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert MagicLinkToken.objects.filter(contact=contact).exists()

    def test_shared_address_with_a_supplier_still_signs_the_client_in(self, client_contact, anon_portal_client):
        """Тот же адрес у поставщика не делает вход неоднозначным: ссылка откроет единственную клиентскую компанию."""
        _contact(_company("Supplier Twin", "333000333", "SUPPLIER"), client_contact.email)

        response = anon_portal_client.post(MAGIC_LINK_URL, {"email": client_contact.email}, format="json")

        assert response.status_code == status.HTTP_200_OK
        token = MagicLinkToken.objects.get()
        assert token.contact_id == client_contact.pk

    def test_link_issued_before_client_type_was_removed_is_refused(
        self, client_contact, client_company, anon_portal_client
    ):
        anon_portal_client.post(MAGIC_LINK_URL, {"email": client_contact.email}, format="json")
        import re

        raw = re.search(r"/auth/magic#token=([\w-]+)", mail.outbox[-1].body).group(1)
        _strip_client(client_company)

        response = anon_portal_client.post(MAGIC_EXCHANGE_URL, {"token": raw}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not PortalSession.objects.exists()

    def test_task_does_not_send_if_type_was_removed_after_the_request(self, client_contact, client_company):
        from portal.services.magic_link import deliver_login_link

        _strip_client(client_company)

        assert deliver_login_link(client_contact.pk) is False
        assert mail.outbox == []


class TestTelegram:
    def test_supplier_cannot_sign_in(self, bot_token, supplier_contact, anon_portal_client):
        init_data = make_telegram_init_data(user_id=supplier_contact.telegram_user_id, bot_token=bot_token)
        unknown = make_telegram_init_data(user_id=999000999, bot_token=bot_token)

        response = anon_portal_client.post(TELEGRAM_URL, {"init_data": init_data}, format="json")
        stranger = anon_portal_client.post(TELEGRAM_URL, {"init_data": unknown}, format="json")

        assert response.status_code == stranger.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data == stranger.data == {"detail": "UNAUTHORIZED"}
        assert not PortalSession.objects.exists()

    def test_own_company_contact_cannot_sign_in(self, bot_token, own, anon_portal_client):
        contact = _contact(own, "boss@railtech.example.uz", telegram_user_id=700300400)

        response = anon_portal_client.post(
            TELEGRAM_URL,
            {"init_data": make_telegram_init_data(user_id=contact.telegram_user_id, bot_token=bot_token)},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not PortalSession.objects.exists()

    def test_client_and_supplier_signs_in(self, bot_token, anon_portal_client):
        contact = _contact(_company("Both", "444000444", "CLIENT", "SUPPLIER"), "both@example.uz", 700500600)

        response = anon_portal_client.post(
            TELEGRAM_URL,
            {"init_data": make_telegram_init_data(user_id=contact.telegram_user_id, bot_token=bot_token)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["company"]["id"] == contact.company_id


class TestLiveSession:
    def test_removing_client_type_makes_the_next_request_401(self, portal_client, client_company):
        assert portal_client.get(ME).status_code == status.HTTP_200_OK

        _strip_client(client_company)

        response = portal_client.get(ME)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {"detail": "UNAUTHORIZED"}

    def test_adding_the_type_back_restores_access(self, portal_client, client_company, client_type):
        _strip_client(client_company)
        assert portal_client.get(ME).status_code == status.HTTP_401_UNAUTHORIZED

        client_company.types.add(client_type)

        assert portal_client.get(ME).status_code == status.HTTP_200_OK

    def test_session_of_client_and_supplier_company_lives(self, client_company):
        from django.conf import settings
        from portal.tests.conftest import PortalAPIClient

        client_company.types.add(_type("SUPPLIER"))
        contact = _contact(client_company, "dual@example.uz")
        session = make_portal_session(contact, client_company, "magic_link")
        api = PortalAPIClient()
        api.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token

        assert api.get(ME).status_code == status.HTTP_200_OK

    def test_session_planted_for_own_company_is_401(self, own):
        from django.conf import settings
        from portal.tests.conftest import PortalAPIClient

        session = make_portal_session(_contact(own, "boss@railtech.example.uz"), own, "magic_link")
        api = PortalAPIClient()
        api.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token

        assert api.get(ME).status_code == status.HTTP_401_UNAUTHORIZED

    def test_session_planted_for_a_supplier_company_is_401(self, supplier_contact):
        """Даже если сессию как-то выпустили (старые данные до K0), кабинет такой компании закрыт."""
        from django.conf import settings
        from portal.tests.conftest import PortalAPIClient

        session = make_portal_session(supplier_contact, supplier_contact.company, "telegram")
        api = PortalAPIClient()
        api.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token

        assert api.get(ME).status_code == status.HTTP_401_UNAUTHORIZED
        for path in ("/requests", "/quotes", "/documents", "/company", "/team", "/catalog"):
            assert api.get("/api/portal/v1" + path).status_code == status.HTTP_401_UNAUTHORIZED, path


class TestInvitation:
    def test_invite_contact_of_supplier_is_refused(self, supplier_contact):
        outcome = invite_contact(supplier_contact, channel="email")

        assert outcome.error == "COMPANY_NOT_CLIENT"
        assert outcome.sent_via == ()
        assert mail.outbox == []
        assert not MagicLinkToken.objects.filter(contact=supplier_contact).exists()
        supplier_contact.refresh_from_db()
        assert supplier_contact.invited_at is None

    def test_invite_contact_of_client_goes(self, client_contact):
        assert invite_contact(client_contact, channel="email").error is None

    def test_invite_team_member_into_company_without_access_is_refused(self, supplier_contact):
        data = {"name": "Коллега", "email": "colleague@supplier.example.uz", "channels": ["email"]}

        with pytest.raises(PermissionDenied):
            invite_team_member(supplier_contact.company, supplier_contact, data)

        assert not Contact.objects.filter(email="colleague@supplier.example.uz").exists()
        assert mail.outbox == []
