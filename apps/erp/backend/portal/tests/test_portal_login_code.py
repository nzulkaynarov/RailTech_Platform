"""B-MAIL-1: вход в кабинет по 6-значному коду из письма — срок, попытки, лимит, одноразовость, Reply-To.

Письмо может идти несколько минут (замер прода: отправка ≈ 2 с, задержка — у почтового провайдера), а ссылка — открыться
на другом устройстве. Поэтому в письме входа и приглашения и ссылка, и код; срок — 60 минут (приглашение — 24 часа).
"""

from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

import pytest
from django.conf import settings
from django.core import mail
from django.utils import timezone
from portal.models import MagicLinkToken, PortalSession
from portal.services import login_code
from portal.services.login_code import LOGIN_CODE_MAX_ATTEMPTS, LOGIN_LINK_TTL, hash_login_code
from portal.tests.conftest import LOCMEM_BACKEND
from rest_framework import status

from notifications.models import EmailLog

MAGIC_LINK_URL = "/api/portal/v1/auth/magic-link"
CODE_URL = "/api/portal/v1/auth/code"
MAGIC_EXCHANGE_URL = "/api/portal/v1/auth/magic"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem_mail(settings, inline_magic_link_task):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


def request_link(client, email):
    return client.post(MAGIC_LINK_URL, {"email": email}, format="json")


def last_code() -> str:
    return re.search(r"(?:Код входа|Login code|Kirish kodi): (\d{6})", mail.outbox[-1].body).group(1)


def last_token() -> str:
    return re.search(r"/auth/magic#token=([\w-]+)", mail.outbox[-1].body).group(1)


def enter(client, email, code, **extra):
    return client.post(CODE_URL, {"email": email, "code": code}, format="json", **extra)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


class TestLoginCode:
    def test_ttl_is_60_minutes(self):
        assert LOGIN_LINK_TTL == timedelta(minutes=60)

    def test_letter_carries_a_code_and_the_code_logs_in(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()

        resp = enter(anon_portal_client, client_contact.email.upper(), code)

        assert resp.status_code == status.HTTP_200_OK, resp.content
        assert resp.data["contact"]["id"] == client_contact.id
        assert resp.data["auth_method"] == "magic_link"
        assert settings.PORTAL_SESSION_COOKIE_NAME in resp.cookies
        assert PortalSession.objects.filter(contact=client_contact).count() == 1

    def test_only_a_keyed_hash_is_stored_and_the_journal_has_no_code(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        row = MagicLinkToken.objects.get(contact=client_contact)
        log = EmailLog.objects.get(template="portal_magic_link")

        assert row.code_hash == hash_login_code(client_contact.pk, code)
        assert code not in row.code_hash
        assert code not in log.body_text and code not in log.body_html
        assert "[REDACTED]" in log.body_text

    def test_code_works_30_minutes_later_and_not_after_60(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        later = timezone.now() + timedelta(minutes=30)
        with mock.patch("django.utils.timezone.now", return_value=later):
            assert enter(anon_portal_client, client_contact.email, code).status_code == 200

        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        expired = timezone.now() + timedelta(minutes=61)
        with mock.patch("django.utils.timezone.now", return_value=expired):
            resp = enter(anon_portal_client, client_contact.email, code)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.data["detail"] == "LOGIN_CODE_INVALID"

    def test_code_is_single_use_and_burns_the_link_of_the_same_letter(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code, token = last_code(), last_token()

        assert enter(anon_portal_client, client_contact.email, code).status_code == 200
        again = enter(anon_portal_client, client_contact.email, code)
        link = anon_portal_client.post(MAGIC_EXCHANGE_URL, {"token": token}, format="json")

        assert again.status_code == 422 and again.data["detail"] == "LOGIN_CODE_INVALID"
        assert link.status_code == status.HTTP_410_GONE
        assert PortalSession.objects.filter(contact=client_contact).count() == 1

    def test_link_burns_the_code_of_the_same_letter(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code, token = last_code(), last_token()

        assert anon_portal_client.post(MAGIC_EXCHANGE_URL, {"token": token}, format="json").status_code == 200
        assert enter(anon_portal_client, client_contact.email, code).status_code == 422

    def test_new_request_kills_the_previous_code(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        first = last_code()
        request_link(anon_portal_client, client_contact.email)
        second = last_code()
        if first == second:  # 1 к миллиону: коды совпали — проверять нечего
            pytest.skip("codes collided")

        old = enter(anon_portal_client, client_contact.email, first)
        new = enter(anon_portal_client, client_contact.email, second)

        assert old.status_code == 422 and old.data["detail"] == "LOGIN_CODE_INVALID"
        assert new.status_code == 200

    def test_five_wrong_codes_lock_with_a_clear_code_even_for_the_right_one(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()

        answers = [enter(anon_portal_client, client_contact.email, wrong(code)) for _ in range(LOGIN_CODE_MAX_ATTEMPTS)]
        right = enter(anon_portal_client, client_contact.email, code)

        assert [a.data["detail"] for a in answers] == ["LOGIN_CODE_INVALID"] * 4 + ["LOGIN_CODE_LOCKED"]
        assert answers[-1].status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert right.status_code == 429 and right.data["detail"] == "LOGIN_CODE_LOCKED"
        assert MagicLinkToken.objects.get(contact=client_contact).code_attempts == LOGIN_CODE_MAX_ATTEMPTS
        assert not PortalSession.objects.exists()

    def test_attempt_cap_holds_in_the_database_without_the_cache(self, client_contact, anon_portal_client):
        """Кэш сброшен (перезапуск Redis) — потолок попыток письма всё равно держит база."""
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        for _ in range(LOGIN_CODE_MAX_ATTEMPTS):
            enter(anon_portal_client, client_contact.email, wrong(code))
        login_code.reset_address_failures(client_contact.email)

        resp = enter(anon_portal_client, client_contact.email, code)

        assert resp.status_code == 422 and resp.data["detail"] == "LOGIN_CODE_INVALID"
        assert not PortalSession.objects.exists()

    def test_new_request_unlocks_with_a_new_code(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        for _ in range(LOGIN_CODE_MAX_ATTEMPTS):
            enter(anon_portal_client, client_contact.email, wrong(code))

        request_link(anon_portal_client, client_contact.email)

        assert enter(anon_portal_client, client_contact.email, last_code()).status_code == 200

    def test_unknown_address_answers_exactly_like_a_known_one(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        known = [enter(anon_portal_client, client_contact.email, wrong(code)) for _ in range(LOGIN_CODE_MAX_ATTEMPTS)]
        # другой IP: лимит входа по IP (10 в минуту) здесь ни при чём
        unknown = [enter(anon_portal_client, "ghost@example.test", "123456", REMOTE_ADDR="198.51.100.7") for _ in range(LOGIN_CODE_MAX_ATTEMPTS)]

        assert [(r.status_code, r.data["detail"]) for r in known] == [
            (r.status_code, r.data["detail"]) for r in unknown
        ]

    def test_request_rate_limit_is_shared_with_the_link(self, settings, client_contact, anon_portal_client):
        """Новый код — тот же запрос письма: не больше `PORTAL_MAGIC_LINK_MAX_PER_HOUR` в час на адрес."""
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 2
        codes = [request_link(anon_portal_client, client_contact.email).status_code for _ in range(3)]
        assert codes == [200, 200, 429]

    def test_invitation_code_logs_in_and_survives_a_login_request(self, client_contact, anon_portal_client):
        from portal.services.invitation import invite_contact

        outcome = invite_contact(client_contact, channel="email")
        invite_code = last_code()
        assert re.fullmatch(r"erp:email_log:\d+", outcome.email_request_key)
        invite_row = MagicLinkToken.objects.get(contact=client_contact, purpose=MagicLinkToken.PURPOSE_INVITE)
        assert invite_row.expires_at - invite_row.created_at >= timedelta(hours=23, minutes=59)

        request_link(anon_portal_client, client_contact.email)  # вход не гасит приглашение

        assert enter(anon_portal_client, client_contact.email, invite_code).status_code == 200

    @pytest.mark.parametrize(
        "body",
        [
            {"email": "a@example.test"},
            {"email": "a@example.test", "code": "12345"},
            {"code": "123456"},
            {"email": "a@example.test", "code": "12345a"},
            {"email": "a@example.test", "code": "123456", "x": 1},
        ],
    )
    def test_bad_body_is_422_validation_error(self, anon_portal_client, body):
        resp = anon_portal_client.post(CODE_URL, body, format="json")
        assert resp.status_code == 422 and resp.data["detail"] == "VALIDATION_ERROR"

    def test_archived_company_is_refused(self, client_contact, client_company, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        code = last_code()
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        resp = enter(anon_portal_client, client_contact.email, code)

        assert resp.status_code in (403, 422)
        assert not PortalSession.objects.exists()


class TestReplyTo:
    def test_login_letter_replies_to_the_manager_of_the_latest_deal(
        self, client_contact, client_company, anon_portal_client
    ):
        from sales.models import Deal

        from accounts.models import CustomUser

        manager = CustomUser.objects.create_user(
            username="manager-mail1", email="manager.mail1@example.test", password="x-Strong-Pass-1"
        )
        Deal.objects.create(company=client_company, manager=manager, title="Поставка")

        request_link(anon_portal_client, client_contact.email)

        assert mail.outbox[-1].reply_to == ["manager.mail1@example.test"]

    def test_no_manager_no_reply_to(self, client_contact, anon_portal_client):
        request_link(anon_portal_client, client_contact.email)
        assert mail.outbox[-1].reply_to == []
