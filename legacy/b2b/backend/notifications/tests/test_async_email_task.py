"""SEC-tail: auth emails (setup-password, reset) dispatch off-thread via Celery.

Pins that:
  * the ``send_transactional_email`` task is a thin wrapper that forwards to the
    single ``send_templated_email`` entry point with the right primitives, and
  * the auth services enqueue the task (``.delay``) instead of sending inline —
    so the ASGI worker never blocks on SMTP and the neutral-200 forgot-password
    endpoint no longer leaks a timing side-channel.
"""

from unittest.mock import patch

import pytest

from notifications.tasks import send_transactional_email


@pytest.mark.django_db
def test_task_forwards_to_send_templated_email(user_factory):
    """The task resolves user_id → CustomUser and forwards all primitives verbatim."""
    user = user_factory(email="recipient@example.com", username="recipient")
    with patch("notifications.emails.send_templated_email") as mocked:
        result = send_transactional_email(
            "reset_password",
            {"first_name": "Rec", "reset_url": "https://x/reset"},
            ["recipient@example.com"],
            channel="transactional",
            user_id=user.pk,
        )
    assert result["status"] == "sent"
    mocked.assert_called_once()
    args, kwargs = mocked.call_args
    assert args[0] == "reset_password"
    assert args[1] == {"first_name": "Rec", "reset_url": "https://x/reset"}
    assert kwargs["to"] == ["recipient@example.com"]
    assert kwargs["channel"] == "transactional"
    assert kwargs["user"] == user


@pytest.mark.django_db
def test_task_tolerates_missing_user_id():
    """user_id=None (or an id that no longer exists) → user=None, no crash."""
    with patch("notifications.emails.send_templated_email") as mocked:
        send_transactional_email("setup_password", {"setup_url": "u"}, ["a@b.co"], user_id=None)
        send_transactional_email("setup_password", {"setup_url": "u"}, ["a@b.co"], user_id=999999)
    assert mocked.call_count == 2
    for _, kwargs in mocked.call_args_list:
        assert kwargs["user"] is None


@pytest.mark.django_db
def test_registration_enqueues_setup_email_not_inline():
    """create_pending_user must enqueue the task, never call send_templated_email inline."""
    from accounts.services.auth import create_pending_user

    with (
        patch("accounts.services.auth.send_transactional_email.delay") as delayed,
        patch("notifications.emails.send_templated_email") as inline,
    ):
        user, error = create_pending_user("newbie@example.com", "New", "Bie")
    assert error is None and user is not None
    inline.assert_not_called()
    delayed.assert_called_once()
    args, kwargs = delayed.call_args
    assert args[0] == "setup_password"
    assert args[2] == ["newbie@example.com"]
    assert kwargs["user_id"] == user.pk


@pytest.mark.django_db
def test_password_reset_enqueues_email_for_active_user(user_factory):
    """send_password_reset_email enqueues for a known active user (off-thread)."""
    user = user_factory(email="active@example.com", username="active", is_active=True)
    with patch("accounts.services.auth.send_transactional_email.delay") as delayed:
        delivered, error = send_password_reset_email_via_service("active@example.com")
    assert delivered is True and error is None
    delayed.assert_called_once()
    args, kwargs = delayed.call_args
    assert args[0] == "reset_password"
    assert args[2] == [user.email]
    assert kwargs["user_id"] == user.pk


@pytest.mark.django_db
def test_password_reset_unknown_email_does_not_enqueue():
    """Unknown address: neutral success, NO task enqueued (no work → no timing leak)."""
    with patch("accounts.services.auth.send_transactional_email.delay") as delayed:
        delivered, error = send_password_reset_email_via_service("ghost@example.com")
    assert delivered is True and error is None
    delayed.assert_not_called()


def send_password_reset_email_via_service(email):
    # Imported lazily so the patch targets resolve against the live module.
    from accounts.services.auth import send_password_reset_email

    return send_password_reset_email(email)
