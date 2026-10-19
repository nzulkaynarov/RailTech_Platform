"""FIX-15 (P-14): лимиты частоты портала — по сессии, а не по IP; отдельные лимиты на вход и акцепт."""

import pytest
from django.core import mail
from portal.tests.conftest import LOCMEM_CHANNELS, PortalAPIClient, make_telegram_init_data
from rest_framework import status
from rest_framework.throttling import SimpleRateThrottle

ME = "/api/portal/v1/me"
MAGIC_LINK = "/api/portal/v1/auth/magic-link"
TELEGRAM = "/api/portal/v1/auth/telegram"
ACCEPT = "/api/portal/v1/quotes/999999/accept"


def set_rate(monkeypatch, scope: str, rate: str) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, rate)


def client_for(session) -> PortalAPIClient:
    client = PortalAPIClient()
    client.cookies["portal_session"] = session.raw_token
    return client


@pytest.fixture(autouse=True)
def _no_broker(settings, inline_magic_link_task):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    mail.outbox.clear()


@pytest.mark.django_db
class TestSessionThrottle:
    def test_session_over_limit_gets_429_with_code(self, monkeypatch, portal_client):
        set_rate(monkeypatch, "portal_session", "3/minute")

        codes = [portal_client.get(ME).status_code for _ in range(3)]
        over = portal_client.get(ME)

        assert codes == [200, 200, 200]
        assert over.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert over.json() == {"detail": "TOO_MANY_REQUESTS"}
        assert int(over["Retry-After"]) > 0

    def test_sessions_are_independent_even_from_one_ip(self, monkeypatch, client_session, other_session):
        """Два клиента за одним NAT не делят счётчик: ключ — id сессии, не IP."""
        set_rate(monkeypatch, "portal_session", "2/minute")
        first, second = client_for(client_session), client_for(other_session)

        for _ in range(2):
            assert first.get(ME, REMOTE_ADDR="203.0.113.7").status_code == 200
        assert first.get(ME, REMOTE_ADDR="203.0.113.7").status_code == 429

        assert second.get(ME, REMOTE_ADDR="203.0.113.7").status_code == 200

    def test_same_session_from_other_ip_shares_the_counter(self, monkeypatch, portal_client):
        """Ключ — сессия: смена IP счётчик не сбрасывает."""
        set_rate(monkeypatch, "portal_session", "2/minute")
        for ip in ("203.0.113.1", "203.0.113.2"):
            assert portal_client.get(ME, REMOTE_ADDR=ip).status_code == 200

        assert portal_client.get(ME, REMOTE_ADDR="203.0.113.3").status_code == 429

    def test_default_anonymous_20_per_minute_by_ip_does_not_apply(self, portal_client):
        """Прежний общий анонимный 20/мин по IP делал Cabinet неработоспособным (экран = пачка запросов)."""
        codes = [portal_client.get(ME, REMOTE_ADDR="203.0.113.9").status_code for _ in range(30)]

        assert set(codes) == {200}

    def test_unauthenticated_request_is_401_not_429(self, monkeypatch, anon_portal_client):
        set_rate(monkeypatch, "portal_session", "1/minute")

        codes = [anon_portal_client.get(ME).status_code for _ in range(3)]

        assert codes == [401, 401, 401]

    def test_unauthenticated_accept_is_401_before_any_throttle(self, monkeypatch, anon_portal_client):
        """Ветка `ip:` ключа не достижима на `BasePortalView`: DRF проверяет аутентификацию раньше лимитов (FIX-11b)."""
        set_rate(monkeypatch, "portal_session", "1/minute")
        set_rate(monkeypatch, "portal_accept", "1/minute")

        codes = [anon_portal_client.post(ACCEPT, {"code": "000000"}, format="json").status_code for _ in range(3)]

        assert codes == [401, 401, 401]

    def test_anonymous_logout_is_the_only_ip_keyed_path(self, monkeypatch, anon_portal_client):
        """Выход без сессии (204) — единственное место, где ключ лимита сессии падает на IP."""
        set_rate(monkeypatch, "portal_session", "2/minute")
        logout = "/api/portal/v1/auth/logout"

        codes = [
            anon_portal_client.post(logout, {}, format="json", REMOTE_ADDR="198.51.100.20").status_code
            for _ in range(3)
        ]
        other_ip = anon_portal_client.post(logout, {}, format="json", REMOTE_ADDR="198.51.100.21")

        assert codes == [204, 204, 429]
        assert other_ip.status_code == 204


@pytest.mark.django_db
class TestAcceptThrottle:
    def test_accept_attempts_are_limited_per_session(self, monkeypatch, portal_client):
        set_rate(monkeypatch, "portal_accept", "2/minute")
        body = {"code": "000000"}

        first = portal_client.post(ACCEPT, body, format="json")
        second = portal_client.post(ACCEPT, body, format="json")
        over = portal_client.post(ACCEPT, body, format="json")

        assert (first.status_code, second.status_code) == (404, 404)  # дошли до вида, лимит ещё не исчерпан
        assert over.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert over.json() == {"detail": "TOO_MANY_REQUESTS"}

    def test_accept_limit_does_not_block_reading(self, monkeypatch, portal_client):
        set_rate(monkeypatch, "portal_accept", "1/minute")
        portal_client.post(ACCEPT, {"code": "000000"}, format="json")
        assert portal_client.post(ACCEPT, {"code": "000000"}, format="json").status_code == 429

        assert portal_client.get(ME).status_code == 200

    def test_accept_limits_are_independent_per_session(self, monkeypatch, client_session, other_session):
        set_rate(monkeypatch, "portal_accept", "1/minute")
        first, second = client_for(client_session), client_for(other_session)
        first.post(ACCEPT, {"code": "000000"}, format="json")

        assert first.post(ACCEPT, {"code": "000000"}, format="json").status_code == 429
        assert second.post(ACCEPT, {"code": "000000"}, format="json").status_code == 404

    def test_other_actions_are_not_counted_in_accept_scope(self, monkeypatch, portal_client):
        set_rate(monkeypatch, "portal_accept", "1/minute")
        for _ in range(3):
            resp = portal_client.post("/api/portal/v1/quotes/999999/reject", {"reason": "дорого"}, format="json")
            assert resp.status_code == 404


@pytest.mark.django_db
class TestLoginThrottle:
    def test_magic_link_requests_are_limited_per_ip(self, monkeypatch, anon_portal_client):
        set_rate(monkeypatch, "portal_login", "3/minute")

        codes = [
            anon_portal_client.post(
                MAGIC_LINK, {"email": f"user{i}@example.com"}, format="json", REMOTE_ADDR="198.51.100.5"
            ).status_code
            for i in range(4)
        ]
        other_ip = anon_portal_client.post(
            MAGIC_LINK, {"email": "user9@example.com"}, format="json", REMOTE_ADDR="198.51.100.6"
        )

        assert codes == [200, 200, 200, 429]
        assert other_ip.status_code == 200

    def test_ip_limit_answers_with_error_code_and_retry_after(self, monkeypatch, anon_portal_client):
        set_rate(monkeypatch, "portal_login", "1/minute")
        anon_portal_client.post(MAGIC_LINK, {"email": "a@example.com"}, format="json")

        over = anon_portal_client.post(MAGIC_LINK, {"email": "b@example.com"}, format="json")

        assert over.status_code == 429
        assert over.json() == {"detail": "TOO_MANY_REQUESTS"}
        assert "Retry-After" in over

    def test_address_limit_holds_across_ips(self, settings, client_contact, anon_portal_client):
        """Один адрес не обойти сменой IP: лимит на адрес (N/час) — отдельный от лимита по IP."""
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 2

        codes = [
            anon_portal_client.post(
                MAGIC_LINK, {"email": client_contact.email}, format="json", REMOTE_ADDR=f"198.51.100.{n}"
            ).status_code
            for n in range(1, 4)
        ]

        assert codes == [200, 200, 429]

    def test_telegram_sign_in_is_limited_per_ip(self, monkeypatch, bot_token, client_contact, anon_portal_client):
        set_rate(monkeypatch, "portal_login", "2/minute")
        init_data = make_telegram_init_data(user_id=client_contact.telegram_user_id, bot_token=bot_token)

        codes = [
            anon_portal_client.post(TELEGRAM, {"init_data": init_data}, format="json", REMOTE_ADDR="198.51.100.5")
            for _ in range(3)
        ]

        assert [c.status_code for c in codes] == [200, 200, 429]

    def test_authenticated_reading_is_not_counted_in_login_scope(self, monkeypatch, portal_client):
        set_rate(monkeypatch, "portal_login", "1/minute")

        assert {portal_client.get(ME).status_code for _ in range(5)} == {200}

    def test_failed_sign_in_attempts_count_too(self, monkeypatch, bot_token, anon_portal_client):
        """Перебор подделок initData упирается в лимит, а не только успешные входы."""
        set_rate(monkeypatch, "portal_login", "2/minute")
        forged = make_telegram_init_data(user_id=1, bot_token="attacker-guess")

        codes = [anon_portal_client.post(TELEGRAM, {"init_data": forged}, format="json").status_code for _ in range(3)]

        assert codes == [401, 401, 429]
