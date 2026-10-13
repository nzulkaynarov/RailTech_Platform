"""Шаблоны писем (M3-CRM-08): все плейсхолдеры подставлены, язык сотрудника, откат на русский."""

import re

import pytest

from app.domain import smtp as domain
from app.services import mail_templates

CONTEXT = {
    "full_name": "Азиз Каримов",
    "email": "aziz@railtech.uz",
    "temporary_password": "Tmp-pass-4321",
    "crm_url": "https://crm.example.com",
    "company": "RailTech",
}


@pytest.mark.parametrize("template", ["invite", "password_reset"])
@pytest.mark.parametrize("lang", ["ru", "uz", "en"])
def test_renders_every_language_without_leftover_placeholders(template: str, lang: str) -> None:
    rendered = mail_templates.render(template, lang, **CONTEXT)
    assert rendered.lang == lang
    assert rendered.subject
    assert not re.search(r"\$[a-z_]+", rendered.subject + rendered.body)
    assert CONTEXT["temporary_password"] in rendered.body
    assert f"{CONTEXT['crm_url']}/login" in rendered.body


@pytest.mark.parametrize("lang", [None, "", "de", "UZ", "en-US"])
def test_language_resolution(lang: str | None) -> None:
    code = mail_templates.resolve_language(lang)
    assert code in mail_templates.LANGUAGES
    if lang and lang[:2].lower() in mail_templates.LANGUAGES:
        assert code == lang[:2].lower()
    else:
        assert code == "ru"


def test_missing_dictionary_falls_back_to_russian() -> None:
    """У «test» только русский файл: любой язык → русское письмо, `lang` в журнале — `ru`."""
    rendered = mail_templates.render(
        "test", "en", full_name="Админ", host="smtp.example", from_email="crm@example.com"
    )
    assert rendered.lang == "ru"
    assert "smtp.example" in rendered.body


def test_missing_placeholder_fails_loudly() -> None:
    values = dict(CONTEXT)
    values.pop("temporary_password")
    with pytest.raises(KeyError):
        mail_templates.render("invite", "ru", **values)


def test_unknown_template_is_an_error() -> None:
    with pytest.raises(mail_templates.TemplateMissingError):
        mail_templates.render("marketing", "ru")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" SMTP.Example.COM. ", "smtp.example.com"),
        ("smtp://relay.example", "relay.example"),
        ("relay.example/", "relay.example"),
        ("", ""),
    ],
)
def test_host_normalization(raw: str, expected: str) -> None:
    assert domain.normalize_host(raw) == expected


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("smtp.example.com", True),
        ("localhost", True),
        ("", False),
        ("smtp.example.com:587", False),
        ("https://smtp.example.com", False),
        ("smtp exam.com", False),
        ("a..b", False),
        ("x" * 64 + ".com", False),
    ],
)
def test_host_problem(host: str, ok: bool) -> None:
    assert (domain.host_problem(host) is None) is ok


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("crm@example.com", True),
        ("", False),
        ("crm@", False),
        ("crm example@x.com", False),
        ("crm@@example.com", False),
        ("crm@example", False),
    ],
)
def test_email_problem(address: str, ok: bool) -> None:
    assert (domain.email_problem(address) is None) is ok


def test_sender_header() -> None:
    assert domain.format_sender("crm@example.com", 'Rail "Tech"') == '"Rail Tech" <crm@example.com>'
    assert domain.format_sender("crm@example.com", "  ") == "crm@example.com"
