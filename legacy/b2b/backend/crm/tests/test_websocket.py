"""Tests for WebSocket consumer access control logic.

These are unit tests for the access-check helpers used by ChatConsumer,
not full ASGI integration tests (which require Channels test tooling +
Redis). They verify the authorization logic in crm.services that the
consumer delegates to.
"""

from unittest.mock import MagicMock


class TestUserCanAccessDealChat:
    """Tests for crm.services.user_can_access_deal_chat."""

    def _make_user(self, authenticated=True, is_superuser=False, is_platform_admin=False, user_id=1):
        user = MagicMock()
        user.is_authenticated = authenticated
        user.is_superuser = is_superuser
        user.is_platform_admin = is_platform_admin
        user.id = user_id
        user.pk = user_id
        return user

    def _make_deal(self, company_id=10, manager_id=None, client_id=None):
        deal = MagicMock()
        deal.company_id = company_id
        deal.manager_id = manager_id
        deal.client_id = client_id
        return deal

    def test_unauthenticated_user_denied(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(authenticated=False)
        deal = self._make_deal()
        assert user_can_access_deal_chat(user, deal) is False

    def test_none_user_denied(self):
        from crm.services import user_can_access_deal_chat

        deal = self._make_deal()
        assert user_can_access_deal_chat(None, deal) is False

    def test_superuser_allowed(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(is_superuser=True)
        deal = self._make_deal()
        assert user_can_access_deal_chat(user, deal) is True

    def test_platform_admin_allowed(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(is_platform_admin=True)
        deal = self._make_deal()
        assert user_can_access_deal_chat(user, deal) is True

    def test_deal_manager_allowed(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(user_id=5)
        deal = self._make_deal(manager_id=5)
        assert user_can_access_deal_chat(user, deal) is True

    def test_deal_client_allowed(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(user_id=7)
        deal = self._make_deal(client_id=7)
        assert user_can_access_deal_chat(user, deal) is True

    def test_company_member_allowed(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(user_id=99)
        deal = self._make_deal(company_id=10)
        user.memberships.filter.return_value.exists.return_value = True
        assert user_can_access_deal_chat(user, deal) is True

    def test_non_member_denied(self):
        from crm.services import user_can_access_deal_chat

        user = self._make_user(user_id=99)
        deal = self._make_deal(company_id=10)
        user.memberships.filter.return_value.exists.return_value = False
        assert user_can_access_deal_chat(user, deal) is False


class TestSendDealMessage:
    """Tests for crm.services.send_deal_message validation logic."""

    def test_empty_message_returns_error(self):
        from crm.services import send_deal_message

        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = True
        user.is_platform_admin = True
        user.id = 1

        deal = MagicMock()
        deal.company_id = 1
        deal.manager_id = 1
        deal.client_id = None

        msg, error = send_deal_message(user, deal, "")
        assert error == "EMPTY_MESSAGE"
        assert msg is None

    def test_whitespace_only_message_returns_error(self):
        from crm.services import send_deal_message

        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = True
        user.is_platform_admin = True
        user.id = 1

        deal = MagicMock()
        deal.company_id = 1
        deal.manager_id = 1
        deal.client_id = None

        msg, error = send_deal_message(user, deal, "   \n\t  ")
        assert error == "EMPTY_MESSAGE"
        assert msg is None

    def test_unauthenticated_user_denied(self):
        from crm.services import send_deal_message

        user = MagicMock()
        user.is_authenticated = False
        user.id = 1

        deal = MagicMock()
        deal.company_id = 1
        deal.manager_id = None
        deal.client_id = None

        msg, error = send_deal_message(user, deal, "hello")
        assert error == "NOT_DEAL_MEMBER"
        assert msg is None
