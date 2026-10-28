"""Письма приглашения и входа в портал — на языке контакта, в трёх локалях ru/uz/en (FIX-23, P-17).

Раньше узбекского каталога не было вовсе (`uz` молча падал в русский), а тесты локалей проверяли пустое. Здесь каждая
локаль проверяется на каждом из двух писем: тема, ключевые фразы текстовой и HTML-частей, `lang` документа и
отсутствие кириллицы там, где текст обязан быть не русским (имя компании и контакта в фикстуре — латиницей).
"""

from __future__ import annotations

import re

import pytest
from django.core import mail
from django.test import override_settings
from portal.tests.conftest import LOCMEM_BACKEND

from notifications.emails import send_templated_email

pytestmark = pytest.mark.django_db

CYRILLIC = re.compile("[А-Яа-яЁё]")
INVITE_URL = "https://cabinet.example.test/auth/magic#token=invite-0001"
LOGIN_URL = "https://cabinet.example.test/auth/magic#token=login-0001"

INVITATION = {
    "contact_name": "Azamat",
    "company_name": "Acme Trading",
    "invite_url": INVITE_URL,
    "telegram_url": "https://t.me/acme_bot",
}
MAGIC_LINK = {"contact_name": "Azamat", "company_name": "Acme Trading", "login_url": LOGIN_URL}

#: (язык, тема, фразы, которые обязаны быть в тексте письма).
EXPECTED = {
    ("portal_invitation", "ru"): (
        "Приглашение в личный кабинет «Acme Trading»",
        ["Здравствуйте, Azamat!", "Вас пригласили в личный кабинет компании «Acme Trading»", "24 часов"],
    ),
    ("portal_invitation", "en"): (
        "Invitation to «Acme Trading» client portal",
        ["Hello, Azamat!", "You have been invited to the client portal of «Acme Trading»", "valid for 24 hours"],
    ),
    ("portal_invitation", "uz"): (
        "«Acme Trading» shaxsiy kabinetiga taklifnoma",
        ["Assalomu alaykum, Azamat!", "«Acme Trading» kompaniyasining shaxsiy kabinetiga taklif qilishdi", "24 soat"],
    ),
    ("portal_magic_link", "ru"): (
        "Вход в личный кабинет",
        ["Здравствуйте, Azamat!", "Для входа в личный кабинет компании «Acme Trading»", "15 минут"],
    ),
    ("portal_magic_link", "en"): (
        "Log in to your client portal",
        ["Hello, Azamat!", "To log in to the client portal of «Acme Trading»", "valid for 15 minutes"],
    ),
    ("portal_magic_link", "uz"): (
        "Shaxsiy kabinetga kirish",
        ["Assalomu alaykum, Azamat!", "«Acme Trading» kompaniyasining shaxsiy kabinetiga kirish", "15 daqiqa"],
    ),
}
CONTEXTS = {"portal_invitation": INVITATION, "portal_magic_link": MAGIC_LINK}
URLS = {"portal_invitation": INVITE_URL, "portal_magic_link": LOGIN_URL}


def send(template, language, **kwargs):
    mail.outbox = []
    send_templated_email(template, CONTEXTS[template], to=["azamat@example.test"], language=language, **kwargs)
    assert len(mail.outbox) == 1
    return mail.outbox[0]


def html_of(message):
    return message.alternatives[0][0]


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
@pytest.mark.parametrize("language", ["ru", "uz", "en"])
@pytest.mark.parametrize("template", ["portal_invitation", "portal_magic_link"])
def test_email_is_rendered_in_the_language_of_the_contact(template, language):
    subject, phrases = EXPECTED[(template, language)]
    message = send(template, language)

    assert message.subject == subject
    for phrase in phrases:
        assert phrase in message.body, f"{template}/{language}: нет фразы {phrase!r} в тексте письма"
    assert URLS[template] in message.body
    html = html_of(message)
    assert f'<html lang="{language}">' in html
    assert URLS[template] in html


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
@pytest.mark.parametrize("language", ["uz", "en"])
@pytest.mark.parametrize("template", ["portal_invitation", "portal_magic_link"])
def test_non_russian_email_has_no_russian_left(template, language):
    """Ни тема, ни текст, ни HTML (шапка, кнопка, подвал) не остаются русскими в uz и en."""
    message = send(template, language)
    for name, text in (("тема", message.subject), ("текст", message.body), ("html", html_of(message))):
        assert not CYRILLIC.search(
            text
        ), f"{template}/{language}: кириллица в части «{name}»: {CYRILLIC.findall(text)[:5]}"


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
@pytest.mark.parametrize("template", ["portal_invitation", "portal_magic_link"])
def test_russian_email_is_russian(template):
    message = send(template, "ru")
    assert CYRILLIC.search(message.body) and CYRILLIC.search(html_of(message))


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
@pytest.mark.parametrize("template", ["portal_invitation", "portal_magic_link"])
@pytest.mark.parametrize("language", ["", "fr", "uz-Cyrl", None])
def test_unknown_language_falls_back_to_russian(template, language):
    message = send(template, language)
    assert message.subject == EXPECTED[(template, "ru")][0]


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
def test_telegram_block_is_translated_in_every_locale():
    expected = {"ru": "войти через Telegram", "en": "log in via Telegram", "uz": "Telegram orqali kirishingiz"}
    for language, phrase in expected.items():
        assert phrase in send("portal_invitation", language).body


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
def test_language_does_not_leak_into_the_caller():
    from django.utils import translation

    with translation.override("ru"):
        send("portal_invitation", "uz")
        assert translation.get_language() == "ru"


# ── Через портал: язык берётся у контакта, а не у того, кто нажал кнопку ─────────────────────────


@pytest.fixture
def locmem(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    mail.outbox = []


@pytest.mark.parametrize("language", ["ru", "uz", "en"])
def test_invitation_through_the_api_goes_out_in_the_invited_language(locmem, portal_client, language):
    response = portal_client.post(
        "/api/portal/v1/team/invite",
        {
            "name": "Dilshod",
            "email": f"dilshod.{language}@example.uz",
            "language": language,
            "channels": ["email"],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["language"] == language
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [f"dilshod.{language}@example.uz"]
    assert "OOO Test Client Company" in mail.outbox[0].subject
    assert f'<html lang="{language}">' in html_of(mail.outbox[0])


@pytest.mark.parametrize(
    ("language", "subject"),
    [("ru", "Вход в личный кабинет"), ("uz", "Shaxsiy kabinetga kirish"), ("en", "Log in to your client portal")],
)
def test_login_link_goes_out_in_the_language_of_the_contact(
    locmem, inline_magic_link_task, anon_portal_client, client_contact, language, subject
):
    client_contact.language = language
    client_contact.save(update_fields=["language"])
    response = anon_portal_client.post("/api/portal/v1/auth/magic-link", {"email": client_contact.email}, format="json")
    assert response.status_code == 200
    assert [m.subject for m in mail.outbox] == [subject]
