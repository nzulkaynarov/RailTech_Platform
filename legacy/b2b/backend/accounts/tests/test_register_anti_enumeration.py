"""Anti-enumeration registration (P2).

Registration must not reveal whether an email already has an account. All three
branches (free / active-account / pending-account) return the SAME neutral 201 and
differ only in which email is ENQUEUED — never in status, body, or (because both
"occupied" branches only enqueue) timing.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

REGISTER_URL = "/api/v1/auth/register/"


def _payload(email):
    return {
        "email": email,
        "first_name": "New",
        "last_name": "User",
        "phone": "+998901234567",
    }


@pytest.mark.django_db
class TestRegisterAntiEnumeration:
    def _enqueued_templates(self, mock_task):
        """Template names passed to send_transactional_email.delay across all calls."""
        return [call.args[0] for call in mock_task.delay.call_args_list]

    def test_free_email_creates_pending_user_and_sends_setup(self, client):
        from accounts.models import CustomUser

        with patch("accounts.services.auth.send_transactional_email") as mock_task:
            response = client.post(REGISTER_URL, _payload("fresh@example.com"), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert self._enqueued_templates(mock_task) == ["setup_password"]
        user = CustomUser.objects.get(email="fresh@example.com")
        assert user.is_active is False

    def test_existing_active_email_sends_existing_account_and_creates_no_second_user(self, client, user_factory):
        from accounts.models import CustomUser

        user_factory(email="active@example.com", username="active", is_active=True)

        with patch("accounts.services.auth.send_transactional_email") as mock_task:
            response = client.post(REGISTER_URL, _payload("active@example.com"), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert self._enqueued_templates(mock_task) == ["register_existing_account"]
        # No duplicate account materialised.
        assert CustomUser.objects.filter(email="active@example.com").count() == 1

    def test_pending_email_resends_setup_and_creates_no_second_user(self, client, user_factory):
        from accounts.models import CustomUser

        user_factory(email="pending@example.com", username="pending", is_active=False)

        with patch("accounts.services.auth.send_transactional_email") as mock_task:
            response = client.post(REGISTER_URL, _payload("pending@example.com"), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert self._enqueued_templates(mock_task) == ["setup_password"]
        assert CustomUser.objects.filter(email="pending@example.com").count() == 1

    def test_three_branches_are_indistinguishable_in_status_and_body(self, client, user_factory):
        """The response an attacker sees is identical across all three branches."""
        user_factory(email="taken-active@example.com", username="ta", is_active=True)
        user_factory(email="taken-pending@example.com", username="tp", is_active=False)

        responses = []
        for email in ("brand-new@example.com", "taken-active@example.com", "taken-pending@example.com"):
            with patch("accounts.services.auth.send_transactional_email"):
                responses.append(client.post(REGISTER_URL, _payload(email), format="json"))

        statuses = {r.status_code for r in responses}
        assert statuses == {status.HTTP_201_CREATED}
        # Same body shape + message; only the echoed (client-supplied) email varies.
        messages = {r.data["message"] for r in responses}
        assert len(messages) == 1
        for resp, email in zip(
            responses, ("brand-new@example.com", "taken-active@example.com", "taken-pending@example.com")
        ):
            assert set(resp.data.keys()) == {"message", "email"}
            assert resp.data["email"] == email

    def test_existing_account_email_carries_login_and_forgot_links(self, client, user_factory):
        """The register_existing_account email is enqueued with sign-in + recover links."""
        user_factory(email="owner@example.com", username="owner", is_active=True)

        with patch("accounts.services.auth.send_transactional_email") as mock_task:
            client.post(REGISTER_URL, _payload("owner@example.com"), format="json")

        template, context = mock_task.delay.call_args.args[0], mock_task.delay.call_args.args[1]
        assert template == "register_existing_account"
        assert "login_url" in context and "forgot_url" in context
        assert context["forgot_url"].endswith("/forgot-password")

    def test_register_existing_account_templates_render(self):
        """The subject/txt/html file templates for the new email exist and render."""
        from notifications.emails import _render_bodies

        subject, text_body, html_body = _render_bodies(
            "register_existing_account",
            {"first_name": "Алиса", "login_url": "https://app/", "forgot_url": "https://app/forgot-password"},
        )
        assert subject
        assert "https://app/forgot-password" in text_body
        assert "https://app/forgot-password" in html_body
