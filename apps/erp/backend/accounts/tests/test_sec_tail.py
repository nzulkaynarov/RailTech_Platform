"""Security-tail batch (audit 2026-07-02): SEC-10 init_superadmin, SEC-12 reset_password.

SEC-10 — the command must key on EMAIL (USERNAME_FIELD), never hijack an unrelated
account whose username equals the email local part, and must not touch an existing
account unless --reset-password is passed (a redeploy used to undo password rotations
and re-activate a disabled superadmin).

SEC-12 — a password reset must not resurrect a deactivated account.
"""

from io import StringIO

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.management import call_command
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import CustomUser
from accounts.services.auth import reset_password

ENV = {"SUPERADMIN_EMAIL": "admin@example.com", "SUPERADMIN_PASSWORD": "Sup3r-Str0ng-Pass!"}


def _run_command(*args):
    out = StringIO()
    call_command("init_superadmin", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_init_superadmin_creates_by_email(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    output = _run_command()
    user = CustomUser.objects.get(email="admin@example.com")
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.check_password(ENV["SUPERADMIN_PASSWORD"])
    assert "created" in output


@pytest.mark.django_db
def test_init_superadmin_does_not_hijack_unrelated_local_part_account(monkeypatch):
    """SEC-10 core case: a regular user whose USERNAME equals the email local part
    must not be promoted; the superadmin is created as a separate account."""
    bystander = CustomUser.objects.create_user(email="someone@else.uz", username="admin", password="x", is_active=True)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    _run_command()
    bystander.refresh_from_db()
    assert not bystander.is_superuser  # untouched
    admin = CustomUser.objects.get(email="admin@example.com")
    assert admin.is_superuser
    assert admin.username == "admin@example.com"  # local part taken → full email


@pytest.mark.django_db
def test_init_superadmin_rerun_leaves_existing_account_alone(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    _run_command()
    admin = CustomUser.objects.get(email="admin@example.com")
    admin.set_password("Rotated-Elsewhere-1!")
    admin.is_active = False  # e.g. deliberately disabled
    admin.save()

    output = _run_command()  # a redeploy re-runs the command

    admin.refresh_from_db()
    assert admin.check_password("Rotated-Elsewhere-1!")  # rotation NOT undone
    assert not admin.is_active  # disable NOT undone
    assert "left untouched" in output


@pytest.mark.django_db
def test_init_superadmin_reset_password_flag_rotates(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    _run_command()
    admin = CustomUser.objects.get(email="admin@example.com")
    admin.set_password("Old-Pass-1!")
    admin.is_active = False
    admin.save()

    output = _run_command("--reset-password")

    admin.refresh_from_db()
    assert admin.check_password(ENV["SUPERADMIN_PASSWORD"])
    assert admin.is_active and admin.is_superuser
    assert "Reset password" in output


def _reset_args(user):
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


@pytest.mark.django_db
def test_reset_password_refuses_deactivated_account():
    user = CustomUser.objects.create_user(
        email="banned@x.uz", username="banned@x.uz", password="Old-Pass-1!", is_active=False
    )
    uidb64, token = _reset_args(user)
    result, error = reset_password(uidb64, token, "New-Strong-Pass-2!")
    assert result is None
    # Same generic code as an unknown user — account state must not leak.
    assert error == "RESET_PASSWORD_INVALID_USER"
    user.refresh_from_db()
    assert not user.is_active
    assert user.check_password("Old-Pass-1!")


@pytest.mark.django_db
def test_reset_password_active_account_still_works_and_stays_active():
    user = CustomUser.objects.create_user(email="ok@x.uz", username="ok@x.uz", password="Old-Pass-1!", is_active=True)
    uidb64, token = _reset_args(user)
    result, error = reset_password(uidb64, token, "New-Strong-Pass-2!")
    assert error is None and result is not None
    user.refresh_from_db()
    assert user.is_active
    assert user.check_password("New-Strong-Pass-2!")
