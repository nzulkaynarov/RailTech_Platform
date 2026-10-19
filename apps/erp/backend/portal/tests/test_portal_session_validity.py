"""FIX-15 (хвосты ревью FIX-14): живая сессия портала и архивность через общий предикат; письмо — через Celery."""

import pathlib
import re
from unittest import mock

import pytest
from django.core import mail
from kombu.exceptions import OperationalError
from portal.models import MagicLinkToken
from portal.services.magic_link import request_magic_link
from portal.services.tokens import hash_token
from portal.tasks import send_magic_link
from portal.tests.conftest import LOCMEM_CHANNELS
from rest_framework import status

from notifications.models import EmailLog

PORTAL = pathlib.Path(__file__).resolve().parents[1]
ME = "/api/portal/v1/me"


@pytest.mark.django_db
class TestLiveSessionValidity:
    def test_session_of_archived_company_is_401(self, portal_client, client_company):
        assert portal_client.get(ME).status_code == 200
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        response = portal_client.get(ME)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {"detail": "UNAUTHORIZED"}

    def test_archived_company_session_is_401_on_every_endpoint(self, portal_client, client_company):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        for path in ("/requests", "/quotes", "/contracts", "/invoices", "/acts", "/documents", "/company", "/team"):
            assert portal_client.get("/api/portal/v1" + path).status_code == 401, path
        assert portal_client.post("/api/portal/v1/requests", {"summary": "x"}, format="json").status_code == 401

    def test_company_back_from_archive_restores_access(self, portal_client, client_company):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])
        assert portal_client.get(ME).status_code == 401

        client_company.is_active = True
        client_company.save(update_fields=["is_active"])

        assert portal_client.get(ME).status_code == 200

    def test_session_of_contact_moved_to_another_company_is_401(self, portal_client, client_contact, other_company):
        """Контакт переведён в другую компанию: сессия, выданная под прежней, больше не открывает её данные."""
        assert portal_client.get(ME).status_code == 200
        client_contact.company = other_company
        client_contact.save(update_fields=["company"])

        assert portal_client.get(ME).status_code == status.HTTP_401_UNAUTHORIZED

    def test_other_company_session_is_not_affected_by_archive(self, portal_client, other_portal_client, client_company):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        assert portal_client.get(ME).status_code == 401
        assert other_portal_client.get(ME).status_code == 200


def test_archive_check_uses_the_common_predicate():
    """Архив снимает компанию со всех поверхностей одним предикатом (`parties.models.core.active_company_q`)."""
    assert "active_company_q" in (PORTAL / "services/access.py").read_text(encoding="utf-8")
    for name in ("authentication.py", "services/magic_link.py", "services/telegram_auth.py", "services/invitation.py"):
        source = (PORTAL / name).read_text(encoding="utf-8")
        assert "active_company_q" in source or "company_in_circulation" in source, name
        assert "company.is_active" not in source, name
        assert "company__is_active" not in source, name


@pytest.fixture
def delay(monkeypatch):
    """Подмена постановки задачи в очередь: брокера в тестах нет, смотрим сам вызов."""
    mocked = mock.Mock()
    monkeypatch.setattr("portal.tasks.send_magic_link.delay", mocked)
    return mocked


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.mark.django_db
class TestMagicLinkMailIsQueued:
    def test_request_only_enqueues_and_sends_nothing_inline(self, client_contact, delay):
        assert request_magic_link(client_contact.email) is True

        delay.assert_called_once_with(client_contact.pk)
        assert mail.outbox == []
        assert not EmailLog.objects.filter(template="portal_magic_link").exists()

    def test_queue_carries_only_the_contact_id_never_the_token(self, client_contact, delay):
        request_magic_link(client_contact.email)

        assert delay.call_args.args == (client_contact.pk,)
        assert delay.call_args.kwargs == {}
        assert not MagicLinkToken.objects.exists()  # токен рождается внутри задачи

    def test_unknown_archived_or_ambiguous_address_enqueues_nothing(self, delay, client_contact, client_company):
        request_magic_link("nobody@example.com")
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])
        request_magic_link(client_contact.email)

        delay.assert_not_called()

    def test_queue_failure_does_not_reveal_a_known_address(self, client_contact, delay):
        """Брокер недоступен: ответ тот же 200, что и для неизвестного адреса (иначе 500 выдал бы контакт)."""
        delay.side_effect = ConnectionError("broker down")

        assert request_magic_link(client_contact.email) is True

    @pytest.mark.parametrize("error", [OperationalError("redis down"), TimeoutError("broker timeout")])
    def test_broker_errors_are_swallowed_with_the_same_answer(self, client_contact, delay, error):
        delay.side_effect = error

        assert request_magic_link(client_contact.email) is True

    def test_unexpected_errors_are_not_masked_as_broker_outage(self, client_contact, delay):
        """Голый `except Exception` прятал и ошибки кода; теперь проглатываются только ошибки брокера (FIX-11b)."""
        delay.side_effect = TypeError("bug in the task signature")

        with pytest.raises(TypeError):
            request_magic_link(client_contact.email)

    def test_task_issues_the_link_and_sends_the_mail(self, client_contact):
        result = send_magic_link.apply(args=[client_contact.pk]).get()

        assert result == {"contact_id": client_contact.pk, "sent": True}
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [client_contact.email]
        log = EmailLog.objects.get(template="portal_magic_link")
        raw = re.search(r"/auth/magic/([\w-]+)", mail.outbox[0].body).group(1)
        assert MagicLinkToken.objects.get(contact=client_contact).token_hash == hash_token(raw) != raw
        assert raw not in log.body_text and raw not in log.body_html

    def test_task_revokes_the_previous_login_link(self, client_contact):
        send_magic_link.apply(args=[client_contact.pk]).get()
        send_magic_link.apply(args=[client_contact.pk]).get()

        valid = [t for t in MagicLinkToken.objects.filter(contact=client_contact) if t.is_valid()]
        assert len(valid) == 1

    def test_task_sends_nothing_if_company_was_archived_meanwhile(self, client_contact, client_company):
        client_company.is_active = False
        client_company.save(update_fields=["is_active"])

        result = send_magic_link.apply(args=[client_contact.pk]).get()

        assert result["sent"] is False
        assert mail.outbox == [] and not MagicLinkToken.objects.exists()

    def test_task_sends_nothing_if_contact_is_gone(self):
        assert send_magic_link.apply(args=[987654]).get()["sent"] is False
        assert mail.outbox == []
