"""FIX-43 (F-9): `core_seed` не переписывает существующие аккаунты.

Раньше пользователь, найденный по username (локальная часть e-mail), получал e-mail из сида, а
пароль перезаписывался при каждом запуске. Теперь недостающие аккаунты создаются, существующие
пропускаются с сообщением — e-mail, пароль, флаги и членства остаются как были.
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounts.models import CompanyMember

User = get_user_model()

SEED_EMAIL = "aziz.kodirov@example.com"
SEED_USERNAME = "aziz.kodirov"


@pytest.fixture(autouse=True)
def _debug_on(settings):
    settings.DEBUG = True
    settings.OWN_COMPANY_ID = None


def _seed():
    out = StringIO()
    call_command("core_seed", stdout=out)
    return out.getvalue()


def test_an_account_found_by_username_keeps_its_email_and_password(db):
    """Настоящий человек с тем же username, но другим e-mail: сид его не «переезжает» и не сбрасывает пароль."""
    real = User.objects.create_user(
        email="aziz@realfirm.example", username=SEED_USERNAME, password="Real-Secret-1!", first_name="Азиз-настоящий"
    )
    password_hash = real.password

    output = _seed()

    real.refresh_from_db()
    assert real.email == "aziz@realfirm.example"
    assert real.password == password_hash
    assert real.check_password("Real-Secret-1!")
    assert real.first_name == "Азиз-настоящий"
    assert not User.objects.filter(email=SEED_EMAIL).exists(), "второго аккаунта с тем же username не появилось"
    assert "aziz@realfirm.example" in output and "пропущен" in output


def test_an_account_with_the_seed_email_keeps_its_password_and_gets_no_new_roles(db):
    """Аккаунт с e-mail сида уже есть: пароль не меняется, членств и ролей ему сид не выдаёт."""
    existing = User.objects.create_user(email=SEED_EMAIL, username="custom_name", password="Changed-By-Owner-9!")
    password_hash = existing.password

    output = _seed()

    existing.refresh_from_db()
    assert existing.password == password_hash
    assert not existing.check_password("Demo1234!")
    assert not CompanyMember.objects.filter(user=existing).exists()
    assert "пропущен" in output


def test_missing_accounts_are_still_created_with_membership_and_roles(db):
    output = _seed()

    created = User.objects.get(email=SEED_EMAIL)
    assert created.check_password("Demo1234!") or created.has_usable_password()
    member = CompanyMember.objects.get(user=created)
    assert member.company_roles.exists()
    assert f"Пользователь создан: {SEED_EMAIL}" in output


def test_a_second_run_changes_nothing(db):
    """Повторный запуск идемпотентен: все аккаунты существуют, пароль, поставленный владельцем, переживает."""
    _seed()
    user = User.objects.get(email=SEED_EMAIL)
    user.set_password("Owner-Changed-It-1!")
    user.save(update_fields=["password"])
    users_before = User.objects.count()
    members_before = CompanyMember.objects.count()

    output = _seed()

    user.refresh_from_db()
    assert user.check_password("Owner-Changed-It-1!")
    assert User.objects.count() == users_before
    assert CompanyMember.objects.count() == members_before
    assert "Пользователь создан" not in output


def test_a_skipped_account_does_not_stop_the_rest_of_the_seed(db):
    User.objects.create_user(email="aziz@realfirm.example", username=SEED_USERNAME, password="x1")

    _seed()

    assert User.objects.filter(email="diana.rakhimova@example.com").exists()
