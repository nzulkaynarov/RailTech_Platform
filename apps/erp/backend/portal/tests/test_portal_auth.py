"""Tests for Portal Authentication (Telegram initData, Magic Link, Logout, Me)."""

import logging
import re
import time
from datetime import timedelta

import pytest
from django.conf import settings
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from parties.models import Contact
from portal.models import MagicLinkToken, PortalSession
from portal.services.magic_link import exchange_magic_link
from portal.services.tokens import hash_token
from portal.tests.conftest import LOCMEM_CHANNELS, make_telegram_init_data
from rest_framework import status

from core.logging import RedactPortalTokenFilter
from notifications.models import EmailLog

MAGIC_LINK_URL = "/api/portal/v1/auth/magic-link"
MAGIC_EXCHANGE_URL = "/api/portal/v1/auth/magic"


@pytest.fixture(autouse=True)
def _locmem_mail(settings, inline_magic_link_task):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


def request_link(client, email):
    return client.post(MAGIC_LINK_URL, {"email": email}, format="json")


def last_raw_token() -> str:
    """Сырой токен из последнего письма: в базе его нет, только в письме клиенту. Ссылка — `…/auth/magic#token=<токен>`."""
    return re.search(r"/auth/magic#token=([\w-]+)", mail.outbox[-1].body).group(1)


def exchange(client, raw: str):
    """`POST /auth/magic {token}` — обмен токена из фрагмента ссылки на сессию (контракт 0.2.0)."""
    return client.post(MAGIC_EXCHANGE_URL, {"token": raw}, format="json")


@pytest.mark.django_db
class TestTelegramAuth:
    def test_telegram_auth_success(self, bot_token, client_contact, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            username=client_contact.telegram_username,
            bot_token=bot_token,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["contact"]["id"] == client_contact.id
        assert data["contact"]["name"] == client_contact.name
        assert data["company"]["id"] == client_contact.company.id
        assert data["can_act"] is True

        # Проверка cookie
        cookie_name = settings.PORTAL_SESSION_COOKIE_NAME
        assert cookie_name in response.cookies
        session_token = response.cookies[cookie_name].value
        # В базе только хеш токена сессии; сырой токен есть лишь в cookie
        session = PortalSession.objects.get(contact=client_contact)
        assert session.token_hash == hash_token(session_token) != session_token

    def test_telegram_auth_invalid_hash(self, bot_token, client_contact, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            bot_token=bot_token,
        )
        tampered = init_data.replace("hash=", "hash=broken1234567890")

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": tampered},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "INVALID_INIT_DATA"

    @pytest.mark.parametrize("bot_token_setting", ["", "TEST_BOT_TOKEN_12345"])
    def test_forged_init_data_is_rejected_even_in_debug(
        self, settings, client_contact, anon_portal_client, bot_token_setting
    ):
        """FIX-02 (аудит P-2): DEBUG и пустой токен бота больше не отключают проверку подписи."""
        settings.DEBUG = True
        settings.TELEGRAM_BOT_TOKEN = bot_token_setting
        forged = make_telegram_init_data(user_id=client_contact.telegram_user_id, bot_token="attacker-guess")

        response = anon_portal_client.post("/api/portal/v1/auth/telegram", {"init_data": forged}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "INVALID_INIT_DATA"
        assert not PortalSession.objects.filter(contact=client_contact).exists()

    def test_telegram_auth_expired(self, bot_token, client_contact, anon_portal_client):
        # auth_date 10 минут назад (> 300с)
        old_auth_date = int(time.time()) - 600
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            bot_token=bot_token,
            auth_date=old_auth_date,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "INVALID_INIT_DATA"

    def test_telegram_auth_unknown_contact(self, bot_token, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=999888777,
            username="unknown_stranger",
            bot_token=bot_token,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "UNAUTHORIZED"

    def test_telegram_username_alone_does_not_log_in(self, bot_token, anon_portal_client, client_company):
        """FIX-14 (P-11): по username не входят и не привязывают чужой telegram_user_id — только по подписанному id."""
        victim = Contact.objects.create(
            company=client_company, name="Жертва", email="victim@example.uz", telegram_username="shared_name"
        )
        init_data = make_telegram_init_data(user_id=777000111, username="shared_name", bot_token=bot_token)

        response = anon_portal_client.post("/api/portal/v1/auth/telegram", {"init_data": init_data}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "UNAUTHORIZED"
        victim.refresh_from_db()
        assert victim.telegram_user_id is None
        assert not PortalSession.objects.exists()

    def test_telegram_archived_company_is_forbidden(
        self, bot_token, client_contact, client_company, anon_portal_client
    ):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])
        init_data = make_telegram_init_data(user_id=client_contact.telegram_user_id, bot_token=bot_token)

        response = anon_portal_client.post("/api/portal/v1/auth/telegram", {"init_data": init_data}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == "FORBIDDEN"
        assert not PortalSession.objects.exists()


@pytest.mark.django_db
class TestMagicLinkAuth:
    def test_magic_link_flow_success(self, client_contact, anon_portal_client):
        # 1. Запрос ссылки: письмо через шаблон ERP и запись в EmailLog
        req_resp = request_link(anon_portal_client, client_contact.email)

        assert req_resp.status_code == status.HTTP_200_OK
        assert req_resp.data["sent"] is True
        assert req_resp.data["email"] == client_contact.email
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [client_contact.email]
        log = EmailLog.objects.get(template="portal_magic_link")
        assert log.status == EmailLog.STATUS_SENT
        assert log.to_emails == [client_contact.email]

        # 2. В базе — только хеш; сырой токен в письме не совпадает ни с одним значением в базе
        raw = last_raw_token()
        token_obj = MagicLinkToken.objects.get(contact=client_contact)
        assert token_obj.token_hash == hash_token(raw) != raw
        assert token_obj.purpose == MagicLinkToken.PURPOSE_LOGIN
        assert token_obj.is_valid() is True
        # ... и в EmailLog токена нет (иначе читатель журнала войдёт за клиента)
        assert raw not in log.body_text and raw not in log.body_html

        # 3. Обмен токена на сессию
        exchange_resp = exchange(anon_portal_client, raw)

        assert exchange_resp.status_code == status.HTTP_200_OK
        assert exchange_resp.data["contact"]["id"] == client_contact.id
        session_cookie = exchange_resp.cookies[settings.PORTAL_SESSION_COOKIE_NAME].value
        session = PortalSession.objects.get(contact=client_contact)
        assert session.token_hash == hash_token(session_cookie) != session_cookie

        # Токен теперь погашен
        token_obj.refresh_from_db()
        assert token_obj.used_at is not None
        assert token_obj.is_valid() is False

    def test_stored_hash_is_not_a_usable_token(self, client_contact, anon_portal_client):
        """Утечка таблицы не даёт входа: сам хеш как токен не принимается."""
        request_link(anon_portal_client, client_contact.email)
        stored_hash = MagicLinkToken.objects.get(contact=client_contact).token_hash

        resp = exchange(anon_portal_client, stored_hash)

        assert resp.status_code == status.HTTP_410_GONE
        assert not PortalSession.objects.exists()

    def test_session_hash_is_not_a_usable_cookie(self, client_session, anon_portal_client):
        anon_portal_client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = client_session.token_hash
        assert anon_portal_client.get("/api/portal/v1/me").status_code == status.HTTP_401_UNAUTHORIZED

    def test_magic_link_unknown_email(self, anon_portal_client):
        req_resp = request_link(anon_portal_client, "unknown.person@example.com")

        # Не раскрываем отсутствие email, отдаем 200 {"sent": true}
        assert req_resp.status_code == status.HTTP_200_OK
        assert req_resp.data["sent"] is True
        assert not MagicLinkToken.objects.exists()
        assert mail.outbox == []

    def test_response_is_identical_for_known_and_unknown_email(self, client_contact, anon_portal_client):
        known = request_link(anon_portal_client, client_contact.email)
        unknown = request_link(anon_portal_client, "nobody@example.com")

        assert known.status_code == unknown.status_code == status.HTTP_200_OK
        assert {k: v for k, v in known.data.items() if k != "email"} == {
            k: v for k, v in unknown.data.items() if k != "email"
        }

    def test_magic_link_expired(self, client_contact, anon_portal_client):
        MagicLinkToken.objects.create(
            token_hash=hash_token("expired_token_123" + "x" * 8),
            contact=client_contact,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        resp = exchange(anon_portal_client, "expired_token_123" + "x" * 8)

        assert resp.status_code == status.HTTP_410_GONE
        assert resp.data["detail"] == "MAGIC_LINK_EXPIRED"

    def test_magic_link_already_used(self, client_contact, anon_portal_client):
        MagicLinkToken.objects.create(
            token_hash=hash_token("used_token_123" + "x" * 8),
            contact=client_contact,
            expires_at=timezone.now() + timedelta(minutes=15),
            used_at=timezone.now() - timedelta(minutes=2),
        )

        resp = exchange(anon_portal_client, "used_token_123" + "x" * 8)

        assert resp.status_code == status.HTTP_410_GONE
        assert resp.data["detail"] == "MAGIC_LINK_EXPIRED"

    def test_second_redemption_of_same_token_is_gone(self, client_contact, anon_portal_client):
        """FIX-14 (P-9): один токен — одна сессия; повтор сразу после погашения — 410."""
        request_link(anon_portal_client, client_contact.email)
        raw = last_raw_token()

        first = exchange(anon_portal_client, raw)
        second = exchange(anon_portal_client, raw)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_410_GONE
        assert second.data["detail"] == "MAGIC_LINK_EXPIRED"
        assert PortalSession.objects.filter(contact=client_contact).count() == 1

    def test_redemption_locks_the_token_row(self, client_contact, anon_portal_client):
        """Погашение — `select_for_update` в транзакции: параллельный запрос ждёт и получает 410."""
        request_link(anon_portal_client, client_contact.email)
        raw = last_raw_token()

        with CaptureQueriesContext(connection) as queries:
            exchange_magic_link(raw)

        sql = [q["sql"] for q in queries.captured_queries]
        assert any("FOR UPDATE" in q and "portal_magiclinktoken" in q for q in sql)

    def test_tokens_are_not_written_to_logs(self, caplog, client_contact, anon_portal_client):
        """FIX-14 (P-9): ни выдача, ни погашение, ни отказ не пишут токен в лог."""
        caplog.set_level(logging.DEBUG)
        request_link(anon_portal_client, client_contact.email)
        raw = last_raw_token()
        exchange(anon_portal_client, raw)
        exchange(anon_portal_client, raw)  # повтор -> отказ с записью в лог
        exchange(anon_portal_client, "some-guessed-token-value")
        session_cookie = anon_portal_client.cookies.get(settings.PORTAL_SESSION_COOKIE_NAME)

        # Записи самого портала (django.request пишет путь запроса — его закрывает фильтр журнала, тест ниже)
        own = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith(("portal", "notifications")))
        assert "Magic link" in own
        assert raw not in own
        assert "some-guessed-token-value" not in own
        assert hash_token(raw) not in own
        if session_cookie is not None:
            assert session_cookie.value not in own

    def test_request_path_token_is_redacted_by_the_log_filter(self):
        """Токен в пути (старые письма, чужие клиенты) не должен попасть в журнал и после снятия маршрута."""
        assert "redact_portal_token" in settings.LOGGING["handlers"]["console"]["filters"]
        record = logging.LogRecord(
            "django.request",
            logging.WARNING,
            __file__,
            1,
            "%s: %s",
            ("Gone", "/api/portal/v1/auth/magic/sEcReT_tok-1"),
            None,
        )

        assert RedactPortalTokenFilter().filter(record) is True

        assert record.getMessage() == "Gone: /api/portal/v1/auth/magic/[REDACTED]"

    def test_request_limit_per_address(self, settings, client_contact, anon_portal_client):
        """FIX-14 (P-10): не больше N запросов в час на адрес; 429 TOO_MANY_REQUESTS."""
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 2

        codes = [request_link(anon_portal_client, client_contact.email).status_code for _ in range(3)]
        over = request_link(anon_portal_client, client_contact.email)

        assert codes == [200, 200, 429]
        assert over.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert over.data["detail"] == "TOO_MANY_REQUESTS"
        assert len(mail.outbox) == 2
        # Другой адрес лимитом первого не затронут
        assert request_link(anon_portal_client, "other.address@example.com").status_code == 200

    def test_limit_does_not_reveal_whether_address_exists(self, settings, anon_portal_client):
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 1

        codes = [request_link(anon_portal_client, "ghost@example.com").status_code for _ in range(2)]

        assert codes == [200, 429]  # так же, как для существующего адреса

    def test_limit_is_case_insensitive(self, settings, client_contact, anon_portal_client):
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 1
        request_link(anon_portal_client, client_contact.email)
        assert request_link(anon_portal_client, client_contact.email.upper()).status_code == 429

    def test_login_request_does_not_burn_invitation(self, client_contact, anon_portal_client):
        """FIX-14 (P-10): запрос ссылки входа гасит только прежние ссылки входа, не приглашение из ERP."""
        invite = MagicLinkToken.objects.create(
            token_hash=hash_token("invite-token-of-sufficient-length"),
            contact=client_contact,
            purpose=MagicLinkToken.PURPOSE_INVITE,
            expires_at=timezone.now() + timedelta(hours=24),
        )

        request_link(anon_portal_client, client_contact.email)
        first_login = MagicLinkToken.objects.get(contact=client_contact, purpose=MagicLinkToken.PURPOSE_LOGIN)
        request_link(anon_portal_client, client_contact.email)

        invite.refresh_from_db()
        first_login.refresh_from_db()
        assert invite.used_at is None
        assert first_login.used_at is not None  # прежняя ссылка входа погашена новой
        assert exchange(anon_portal_client, "invite-token-of-sufficient-length").status_code == 200

    def test_ambiguous_email_sends_nothing_and_logs_no_address(
        self, caplog, client_contact, other_company, anon_portal_client
    ):
        """FIX-14 (P-16): один адрес у активных контактов разных компаний — письма нет, ответ как обычно."""
        Contact.objects.create(company=other_company, name="Двойник", email=client_contact.email.upper())
        caplog.set_level(logging.DEBUG)

        resp = request_link(anon_portal_client, client_contact.email)

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["sent"] is True
        assert mail.outbox == []
        assert not MagicLinkToken.objects.exists()
        assert client_contact.email.lower() not in caplog.text.lower()
        assert any("several companies" in r.getMessage() for r in caplog.records)

    def test_same_email_twice_in_one_company_is_not_ambiguous(self, client_contact, anon_portal_client):
        Contact.objects.create(company=client_contact.company, name="Коллега", email=client_contact.email)

        request_link(anon_portal_client, client_contact.email)

        assert len(mail.outbox) == 1

    def test_archived_company_gets_no_link(self, client_contact, client_company, anon_portal_client):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        resp = request_link(anon_portal_client, client_contact.email)

        assert resp.status_code == status.HTTP_200_OK  # ответ как для неизвестного адреса
        assert mail.outbox == []
        assert not MagicLinkToken.objects.exists()

    def test_ambiguity_ignores_archived_companies(self, client_contact, other_company, anon_portal_client):
        """Дубль в архивной компании адрес неоднозначным не делает."""
        other_company.is_active = False
        other_company.save(update_fields=["is_active"])
        Contact.objects.create(company=other_company, name="Архивный", email=client_contact.email)

        request_link(anon_portal_client, client_contact.email)

        assert len(mail.outbox) == 1

    def test_link_issued_before_archiving_is_refused(self, client_contact, client_company, anon_portal_client):
        """FIX-14: компанию архивировали после выдачи ссылки — вход 403, сессии нет."""
        request_link(anon_portal_client, client_contact.email)
        raw = last_raw_token()
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        resp = exchange(anon_portal_client, raw)

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["detail"] == "FORBIDDEN"
        assert not PortalSession.objects.exists()


@pytest.mark.django_db
class TestMagicLinkExchange:
    """`POST /auth/magic {token}` по контракту 0.3.0; устаревший `GET /auth/magic/{token}` снят (FIX-25)."""

    def login_token(self, client, contact):
        request_link(client, contact.email)
        return last_raw_token()

    def invite_token(self, contact, raw="invite-token-of-sufficient-length"):
        MagicLinkToken.objects.create(
            token_hash=hash_token(raw),
            contact=contact,
            purpose=MagicLinkToken.PURPOSE_INVITE,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        return raw

    def test_link_in_the_email_carries_the_token_in_the_fragment_only(self, client_contact, anon_portal_client):
        from urllib.parse import urlsplit

        raw = self.login_token(anon_portal_client, client_contact)
        link = re.search(r"http\S+/auth/magic\S*", mail.outbox[-1].body).group(0)
        parts = urlsplit(link)

        assert (parts.scheme, parts.netloc, parts.path) == ("http", "cabinet.localhost", "/auth/magic")
        assert parts.query == "" and parts.fragment == f"token={raw}"
        assert raw not in parts.path and raw not in parts.query

    def test_invitation_link_has_the_same_form(self, client_contact):
        from portal.services.invitation import invite_contact_to_portal

        result, error = invite_contact_to_portal(client_contact, channel="email")

        assert error is None and result["email_sent"] is True
        raw = re.search(r"/auth/magic#token=([\w-]+)", mail.outbox[-1].body).group(1)
        stored = MagicLinkToken.objects.get(contact=client_contact)
        assert stored.purpose == MagicLinkToken.PURPOSE_INVITE and stored.token_hash == hash_token(raw)
        assert f"/auth/magic/{raw}" not in mail.outbox[-1].body

    def test_post_exchanges_login_token_for_a_session(self, client_contact, anon_portal_client):
        from portal.tests.contract_support import check_response, component

        raw = self.login_token(anon_portal_client, client_contact)

        resp = exchange(anon_portal_client, raw)

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert check_response(body, component("Me")) == []
        assert body["auth_method"] == "magic_link" and body["contact"]["id"] == client_contact.id
        cookie = resp.cookies[settings.PORTAL_SESSION_COOKIE_NAME]
        assert cookie["httponly"] and cookie.value
        assert PortalSession.objects.get(contact=client_contact).auth_method == "magic_link"
        assert anon_portal_client.get("/api/portal/v1/me").status_code == status.HTTP_200_OK

    def test_post_accepts_the_invitation_token_too(self, client_contact, anon_portal_client):
        raw = self.invite_token(client_contact)

        assert exchange(anon_portal_client, raw).status_code == status.HTTP_200_OK

    def test_unknown_token_is_410(self, anon_portal_client):
        resp = exchange(anon_portal_client, "unknown-token-of-sufficient-length")

        assert resp.status_code == status.HTTP_410_GONE
        assert resp.json() == {"detail": "MAGIC_LINK_EXPIRED"}
        assert not PortalSession.objects.exists()

    def test_expired_and_used_tokens_are_410(self, client_contact, anon_portal_client):
        for raw, kwargs in (
            ("expired-token-of-sufficient-length", {"expires_at": timezone.now() - timedelta(minutes=1)}),
            (
                "used-token-of-sufficient-length-1",
                {"expires_at": timezone.now() + timedelta(minutes=15), "used_at": timezone.now()},
            ),
        ):
            MagicLinkToken.objects.create(token_hash=hash_token(raw), contact=client_contact, **kwargs)
            resp = exchange(anon_portal_client, raw)
            assert resp.status_code == status.HTTP_410_GONE
            assert resp.json() == {"detail": "MAGIC_LINK_EXPIRED"}

    def test_archived_company_is_403_forbidden(self, client_contact, client_company, anon_portal_client):
        raw = self.invite_token(client_contact)
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        resp = exchange(anon_portal_client, raw)

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json() == {"detail": "FORBIDDEN"}
        assert settings.PORTAL_SESSION_COOKIE_NAME not in resp.cookies
        assert not PortalSession.objects.exists()
        assert MagicLinkToken.objects.get(contact=client_contact).used_at is None  # токен не сожжён отказом

    @pytest.mark.parametrize(
        "body",
        [{}, {"token": ""}, {"token": "x" * 15}, {"token": "x" * 513}, {"token": 12345678901234567}, {"token": None}],
    )
    def test_invalid_body_is_422_validation_error(self, anon_portal_client, body):
        resp = anon_portal_client.post(MAGIC_EXCHANGE_URL, body, format="json")

        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "VALIDATION_ERROR"}

    def test_token_length_bounds(self, anon_portal_client):
        assert exchange(anon_portal_client, "x" * 16).status_code == status.HTTP_410_GONE  # допустимая длина
        assert exchange(anon_portal_client, "x" * 512).status_code == status.HTTP_410_GONE

    def test_extra_fields_are_refused(self, client_contact, anon_portal_client):
        """Контракт: `additionalProperties: false` (хвост ревью FIX-20) — лишнее поле не принимается молча."""
        raw = self.login_token(anon_portal_client, client_contact)

        resp = anon_portal_client.post(MAGIC_EXCHANGE_URL, {"token": raw, "next": "/x"}, format="json")

        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "VALIDATION_ERROR"}
        assert not PortalSession.objects.exists()
        assert exchange(anon_portal_client, raw).status_code == status.HTTP_200_OK  # токен не сожжён отказом

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_legacy_path_route_is_gone(self, anon_portal_client, client_contact, method):
        """`GET /auth/magic/{token}` снят в 0.3.0 (FIX-25): токен в пути — 404, сессия не выдаётся, токен не гасится."""
        raw = self.login_token(anon_portal_client, client_contact)

        resp = getattr(anon_portal_client, method)(f"{MAGIC_EXCHANGE_URL}/{raw}")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert not PortalSession.objects.exists()
        assert exchange(anon_portal_client, raw).status_code == status.HTTP_200_OK

    def test_get_on_the_exchange_url_is_not_an_endpoint(self, anon_portal_client):
        assert anon_portal_client.get(MAGIC_EXCHANGE_URL).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert anon_portal_client.get(MAGIC_EXCHANGE_URL).json() == {"detail": "NOT_FOUND"}


@pytest.mark.django_db
class TestLogoutAndMe:
    def test_me_authenticated(self, portal_client, client_contact, client_company):
        response = portal_client.get("/api/portal/v1/me")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["contact"]["id"] == client_contact.id
        assert data["contact"]["name"] == client_contact.name
        assert data["company"]["id"] == client_company.id
        assert data["can_act"] is True

    def test_me_unauthenticated(self, anon_portal_client):
        response = anon_portal_client.get("/api/portal/v1/me")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "UNAUTHORIZED"

    def test_logout(self, portal_client, client_session):
        assert PortalSession.objects.filter(token_hash=hash_token(client_session.raw_token)).exists()

        response = portal_client.post("/api/portal/v1/auth/logout")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Сессия удалена
        assert not PortalSession.objects.filter(token_hash=hash_token(client_session.raw_token)).exists()

        # Повторный запрос /me теперь 401
        me_resp = portal_client.get("/api/portal/v1/me")
        assert me_resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert me_resp.data["detail"] == "UNAUTHORIZED"


@pytest.mark.django_db
class TestAccessLog:
    """FIX-15 (хвост ревью FIX-14): журнал запросов идёт через Django-логирование и фильтр токена; Daphne -v 0."""

    @staticmethod
    def _console_stream():
        import io

        from django.utils.module_loading import import_string

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        for name in settings.LOGGING["handlers"]["console"]["filters"]:
            handler.addFilter(import_string(settings.LOGGING["filters"][name]["()"])())
        return stream, handler

    def test_request_line_is_written_without_the_token(self, anon_portal_client):
        stream, handler = self._console_stream()
        access = logging.getLogger("core.access")
        access.addHandler(handler)
        access.setLevel(logging.INFO)
        try:
            anon_portal_client.get("/api/portal/v1/auth/magic/sEcReT-tok_1?next=/x")
            anon_portal_client.get("/api/portal/v1/me")
        finally:
            access.removeHandler(handler)

        journal = stream.getvalue()
        assert "GET /api/portal/v1/auth/magic/[REDACTED] 404" in journal
        assert "GET /api/portal/v1/me 401" in journal
        assert "sEcReT-tok_1" not in journal
        assert "next=" not in journal  # строка запроса в журнал не пишется

    def test_error_responses_built_from_exceptions_are_logged(self, anon_portal_client):
        """FIX-11b: ответы, рождённые исключением (404 Django), тоже пишут строку;
        токен в строке — [REDACTED]."""
        stream, handler = self._console_stream()
        access = logging.getLogger("core.access")
        access.addHandler(handler)
        access.setLevel(logging.INFO)
        try:
            gone = anon_portal_client.get("/api/portal/v1/auth/magic/Fix11b-tok_2")
            missing = anon_portal_client.get("/api/portal/v1/no-such-endpoint/Fix11b-tok_2")
        finally:
            access.removeHandler(handler)

        assert (gone.status_code, missing.status_code) == (404, 404)
        lines = stream.getvalue().splitlines()
        assert any(line.startswith("GET /api/portal/v1/auth/magic/[REDACTED] 404 ") for line in lines), lines
        assert any(line.startswith("GET /api/portal/v1/no-such-endpoint/Fix11b-tok_2 404 ") for line in lines), lines
        assert "Fix11b-tok_2" not in "".join(line for line in lines if "/auth/magic/" in line)

    def test_exception_escaping_the_chain_is_logged_as_500_and_reraised(self, rf):
        from core.logging import AccessLogMiddleware

        def boom(request):
            raise RuntimeError("boom")

        stream, handler = self._console_stream()
        access = logging.getLogger("core.access")
        access.addHandler(handler)
        access.setLevel(logging.INFO)
        try:
            with pytest.raises(RuntimeError):
                AccessLogMiddleware(boom)(rf.get("/api/portal/v1/auth/magic/Fix11b-tok_3"))
        finally:
            access.removeHandler(handler)

        journal = stream.getvalue()
        assert journal.startswith("GET /api/portal/v1/auth/magic/[REDACTED] 500 ")
        assert "Fix11b-tok_3" not in journal

    def test_access_log_middleware_is_enabled(self):
        assert "core.logging.AccessLogMiddleware" in settings.MIDDLEWARE

    def test_every_handler_on_the_django_logger_redacts_the_token(self):
        """`django.request` пишет `Gone: <путь с токеном>`; у логгера `django` из DEFAULT_LOGGING свой обработчик
        без фильтра (виден при DEBUG=True, то есть на стенде) — он заменён на наш `console` с фильтром токена."""
        logger = logging.getLogger("django.request")
        handlers = []
        while logger is not None:
            handlers += logger.handlers
            logger = logger.parent if logger.propagate else None
        own = [h for h in handlers if not type(h).__module__.startswith("_pytest")]

        assert own, "у django.request нет обработчиков журнала"
        for handler in own:
            assert any(isinstance(f, RedactPortalTokenFilter) for f in handler.filters), handler
