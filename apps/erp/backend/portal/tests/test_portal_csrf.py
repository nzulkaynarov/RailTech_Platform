"""FIX-15 (C-12): CSRF для сессии в cookie — только JSON и обязательный Idempotency-Key на изменяющих запросах."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from portal.models import PortalSession
from portal.tests.conftest import PortalAPIClient
from rest_framework import status

from crm.models import Deal

API = "/api/portal/v1"

UNSAFE_ENDPOINTS = [
    ("post", "/auth/telegram", {"init_data": "x"}),
    ("post", "/auth/magic-link", {"email": "a@example.com"}),
    ("post", "/auth/magic/some-token", None),
    ("post", "/auth/logout", None),
    ("post", "/requests", {"summary": "Нужны болты"}),
    ("post", "/quotes/1/accept", {"code": "123456"}),
    ("post", "/quotes/1/reject", {"reason": "дорого"}),
    ("post", "/contracts/1/sign", {}),
    ("post", "/acts/1/accept", {}),
    ("post", "/acts/1/return", {"reason": "брак"}),
    ("post", "/team/invite", {"name": "Коллега", "email": "colleague@example.com"}),
    ("post", "/uploads", None),
    ("patch", "/company", {"name": "Новое имя"}),
]


@pytest.fixture
def raw_client(client_session):
    """Клиент с живой сессией и БЕЗ автоподстановки Idempotency-Key."""
    client = PortalAPIClient()
    client.auto_idempotency_key = False
    client.cookies["portal_session"] = client_session.raw_token
    return client


@pytest.mark.django_db
class TestIdempotencyKeyRequired:
    @pytest.mark.parametrize("method,path,body", UNSAFE_ENDPOINTS)
    def test_unsafe_request_without_key_is_400(self, raw_client, method, path, body):
        response = getattr(raw_client, method)(API + path, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"detail": "IDEMPOTENCY_KEY_REQUIRED"}

    def test_blank_key_is_400(self, raw_client):
        response = raw_client.post(API + "/requests", {"summary": "x"}, format="json", HTTP_IDEMPOTENCY_KEY="   ")

        assert response.status_code == 400
        assert response.json() == {"detail": "IDEMPOTENCY_KEY_REQUIRED"}

    def test_request_without_key_changes_nothing(self, raw_client, client_company):
        before = Deal.objects.filter(company=client_company).count()

        raw_client.post(API + "/requests", {"summary": "Нужны болты"}, format="json")

        assert Deal.objects.filter(company=client_company).count() == before

    def test_sign_out_without_key_keeps_the_session(self, raw_client, client_session):
        raw_client.post(API + "/auth/logout")

        assert PortalSession.objects.filter(pk=client_session.pk).exists()

    def test_put_is_not_guarded_because_browsers_preflight_it(self, raw_client):
        """PUT/DELETE «непростые»: междоменный вызов уходит в CORS-preflight, который пускает лишь origin Cabinet."""
        response = raw_client.put(API + "/company", {"name": "Новое имя"}, format="json")

        assert response.status_code == 200

    def test_reading_needs_no_key(self, raw_client):
        assert raw_client.get(API + "/me").status_code == 200
        assert raw_client.get(API + "/requests").status_code == 200

    def test_with_key_request_goes_through(self, raw_client, client_company):
        response = raw_client.post(
            API + "/requests", {"summary": "Нужны болты"}, format="json", HTTP_IDEMPOTENCY_KEY="k-0001"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Deal.objects.filter(company=client_company, title="Нужны болты").count() == 1

    def test_same_key_replays_instead_of_creating_a_second_request(self, raw_client, client_company):
        first = raw_client.post(API + "/requests", {"summary": "Болты"}, format="json", HTTP_IDEMPOTENCY_KEY="k-dup")
        second = raw_client.post(API + "/requests", {"summary": "Болты"}, format="json", HTTP_IDEMPOTENCY_KEY="k-dup")

        assert first.status_code == second.status_code == 201
        assert second["Idempotent-Replay"] == "true"
        assert Deal.objects.filter(company=client_company, title="Болты").count() == 1

    def test_same_key_of_another_session_is_not_replayed(self, client_session, other_session):
        """Ключ клиента выбирает сам: чужой ответ по такому же ключу получить нельзя."""
        results = []
        for session in (client_session, other_session):
            client = PortalAPIClient()
            client.auto_idempotency_key = False
            client.cookies["portal_session"] = session.raw_token
            results.append(
                client.post(API + "/requests", {"summary": "Болты"}, format="json", HTTP_IDEMPOTENCY_KEY="shared-key")
            )

        assert [r.status_code for r in results] == [201, 201]
        assert "Idempotent-Replay" not in results[1]
        assert results[0].json()["id"] != results[1].json()["id"]

    def test_sign_in_response_with_cookie_is_not_replayed_without_cookie(
        self, bot_token, client_contact, anon_portal_client
    ):
        """Повтор входа с тем же ключом не должен вернуть 200 без Set-Cookie: ответ с cookie не кэшируется."""
        from portal.tests.conftest import make_telegram_init_data

        init_data = make_telegram_init_data(user_id=client_contact.telegram_user_id, bot_token=bot_token)
        anon_portal_client.auto_idempotency_key = False
        kwargs = {"format": "json", "HTTP_IDEMPOTENCY_KEY": "same-login-key"}

        first = anon_portal_client.post(API + "/auth/telegram", {"init_data": init_data}, **kwargs)
        second = anon_portal_client.post(API + "/auth/telegram", {"init_data": init_data}, **kwargs)

        assert first.status_code == second.status_code == 200
        assert "portal_session" in first.cookies
        assert "portal_session" in second.cookies

    def test_other_api_spaces_are_not_affected(self, anon_portal_client):
        """Требование относится к /api/portal/*; публичные страницы и ERP-API живут по своим правилам."""
        anon_portal_client.auto_idempotency_key = False

        response = anon_portal_client.post("/api/v1/auth/token/", {"email": "a@b.uz", "password": "x"}, format="json")

        assert response.json().get("detail") != "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.django_db
class TestOnlyJson:
    def test_form_encoded_body_is_415(self, portal_client):
        response = portal_client.post(API + "/requests", "summary=x", content_type="application/x-www-form-urlencoded")

        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        assert response.json() == {"detail": "UNSUPPORTED_MEDIA_TYPE"}

    def test_text_plain_body_is_415(self, portal_client):
        """text/plain и form — «простые» типы междоменной формы: JSON-only закрывает их."""
        response = portal_client.post(API + "/requests", '{"summary": "x"}', content_type="text/plain")

        assert response.status_code == 415

    def test_multipart_body_outside_uploads_is_415(self, portal_client):
        response = portal_client.post(API + "/requests", {"summary": "x"}, format="multipart")

        assert response.status_code == 415

    def test_json_with_charset_is_accepted(self, portal_client):
        response = portal_client.post(
            API + "/requests", '{"summary": "Болты"}', content_type="application/json; charset=utf-8"
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_uploads_keep_multipart(self, portal_client):
        """Файл нельзя передать JSON'ом (Q-14): /uploads — единственное исключение, защищено заголовком-ключом."""
        upload = SimpleUploadedFile("spec.pdf", b"%PDF-1.4 test", content_type="application/pdf")

        response = portal_client.post(API + "/uploads", {"file": upload}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED

    def test_uploads_do_not_accept_other_types(self, portal_client):
        response = portal_client.post(API + "/uploads", "file=x", content_type="application/x-www-form-urlencoded")

        assert response.status_code == 415

    def test_bodyless_post_is_fine(self, portal_client, client_session):
        response = portal_client.post(API + "/auth/logout")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not PortalSession.objects.filter(pk=client_session.pk).exists()

    def test_missing_key_is_reported_before_media_type(self, raw_client):
        response = raw_client.post(API + "/requests", "summary=x", content_type="text/plain")

        assert response.status_code == 400
        assert response.json() == {"detail": "IDEMPOTENCY_KEY_REQUIRED"}

    def test_get_with_any_content_type_is_fine(self, portal_client):
        assert portal_client.get(API + "/me", content_type="text/plain").status_code == 200
