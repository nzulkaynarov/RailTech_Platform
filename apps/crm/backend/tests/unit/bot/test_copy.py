"""Сторож текстов бота: термины глоссария и типографика (дизайн-аудит 2026-10-11, Q-015/Q-016)."""

import re

import pytest

from app.bot.commands import COMMANDS
from app.bot.keyboards import LANGUAGE_LABELS
from app.schemas.settings import LocalizedText, TextsSettings

TEXTS = TextsSettings()
FIELDS = [name for name, value in TEXTS if isinstance(value, LocalizedText)]


def _all(language: str) -> list[str]:
    texts = [getattr(getattr(TEXTS, name), language) for name in FIELDS]
    return texts + [text for _, text in COMMANDS[language]]


# Человек для клиента — только «менеджер» (Q-015); бот не обещает «уточнить» сам (Q-016).
@pytest.mark.parametrize(
    ("language", "forbidden"),
    [
        ("ru", r"коллег|сотрудник|уточню"),
        ("uz", r"hamkasb|xodim|aniqlayman"),
        ("en", r"colleague|\bperson\b|check with"),
    ],
)
def test_client_texts_speak_of_a_manager(language: str, forbidden: str) -> None:
    offenders = [text for text in _all(language) if re.search(forbidden, text, re.IGNORECASE)]
    assert offenders == []


def test_uzbek_uses_official_latin_apostrophes() -> None:
    texts = [*_all("uz"), LANGUAGE_LABELS["uz"]]
    assert [t for t in texts if re.search(r"['‘’`]", t)] == []  # только ʻ (U+02BB) и ʼ (U+02BC)
    assert [t for t in texts if re.search(r"[oOgG]ʼ", t)] == []  # после o/g — ʻ, не ʼ


def test_english_has_no_russian_quotes() -> None:
    assert [t for t in _all("en") if re.search(r"[«»]", t)] == []


@pytest.mark.parametrize("language", ["ru", "uz", "en"])
def test_unsupported_message_does_not_promise_voice_recognition(language: str) -> None:
    text = TEXTS.unsupported_message.get(language)  # type: ignore[arg-type]
    assert not re.search(r"понимаю только|faqat|understand text, files and voice", text)


def test_fallback_offers_a_manager_in_every_language() -> None:
    assert "менеджер" in TEXTS.fallback.ru
    assert "menejer" in TEXTS.fallback.uz
    assert "manager" in TEXTS.fallback.en
    assert TEXTS.handoff_offer_yes.ru == "Позвать менеджера"
