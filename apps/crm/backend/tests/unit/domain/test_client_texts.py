"""Тексты клиенту D1-9 (SPEC-v3 §8): три языка, без внутренних терминов, с нужными подстановками."""

import re

import pytest

from app.domain import client_texts as t

LANGS = ("ru", "uz", "en")
#: Внутренние слова не должны попадать к клиенту: «лид», «сделка», «CRM», коды вида L-0001.
FORBIDDEN = re.compile(r"\bлид|сделк|\bcrm\b|\blead\b|\bdeal\b|\bL-\d|escalat", re.IGNORECASE)


def everything(language: str) -> list[str]:
    mail = t.web_confirmation_mail(language, "Алишер", "RailTech", "https://t.me/b?start=x")
    accepted = t.request_accepted_mail(
        language, "Алишер", "ЗВ-2026-001", "https://cabinet.example.com"
    )
    return [
        t.web_confirmation_bot(language, "Алишер"),
        mail.subject,
        mail.body,
        t.request_accepted_bot(language, "ЗВ-2026-001"),
        accepted.subject,
        accepted.body,
        t.invite_bot(language, "Алишер", "RailTech"),
        t.start_deal(language, "Поставка рельсов"),
        t.start_lead_bound(language),
        t.start_link_stale(language),
        t.open_cabinet_label(language),
    ]


@pytest.mark.parametrize("language", LANGS)
def test_no_internal_terms_reach_the_client(language: str) -> None:
    for text in everything(language):
        assert not FORBIDDEN.search(text), text


def test_the_three_languages_differ() -> None:
    texts = {language: everything(language) for language in LANGS}
    for index in range(len(texts["ru"])):
        assert len({texts[language][index] for language in LANGS}) == 3, index


def test_unknown_language_falls_back_to_russian() -> None:
    assert t.web_confirmation_bot("de", "Иван") == t.web_confirmation_bot("ru", "Иван")
    assert t.web_confirmation_bot(None, "Иван") == t.web_confirmation_bot("ru", "Иван")


@pytest.mark.parametrize("language", LANGS)
def test_web_confirmation_mail_carries_name_and_bot_link_but_never_the_request_text(
    language: str,
) -> None:
    """Письмо уходит на любой указанный адрес: чужой текст запроса оно не пересылает."""
    mail = t.web_confirmation_mail(language, "Алишер", "RailTech", "https://t.me/b?start=x")
    assert "Алишер" in mail.body
    assert "https://t.me/b?start=x" in mail.body
    assert mail.body.rstrip().endswith("RailTech")
    assert "«" not in mail.body


def test_web_confirmation_mail_without_bot_is_still_whole() -> None:
    mail = t.web_confirmation_mail("ru", "", "", None)
    assert mail.body.startswith("Здравствуйте!")
    assert "t.me" not in mail.body


@pytest.mark.parametrize("language", LANGS)
def test_request_accepted_names_the_number_and_points_to_the_cabinet(language: str) -> None:
    assert "ЗВ-2026-001" in t.request_accepted_bot(language, "ЗВ-2026-001")
    mail = t.request_accepted_mail(language, "Ann", "ЗВ-2026-001", "https://cabinet.example.com")
    assert "ЗВ-2026-001" in mail.subject
    assert "https://cabinet.example.com" in mail.body


def test_request_accepted_without_number_has_no_double_space() -> None:
    assert t.request_accepted_bot("ru", "").startswith("Заявка принята")
    assert "  " not in t.request_accepted_bot("en", "")


def test_start_deal_quotes_the_title_only_when_known() -> None:
    assert "«Рельсы Р65»" in t.start_deal("ru", "Рельсы Р65")
    assert "«" not in t.start_deal("ru", None)
