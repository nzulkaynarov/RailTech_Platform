"""Inline-клавиатуры клиентского бота."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.schemas.settings import AppSettings, Language

CONSENT_ACCEPT = "consent:accept"
LANGUAGE_PREFIX = "lang:"
LANGUAGE_LABELS: dict[Language, str] = {"ru": "Русский", "uz": "O'zbekcha", "en": "English"}


def consent(settings: AppSettings, language: Language) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=settings.texts.consent_button.get(language), callback_data=CONSENT_ACCEPT
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def languages() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=label, callback_data=f"{LANGUAGE_PREFIX}{code}")
        for code, label in LANGUAGE_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])
