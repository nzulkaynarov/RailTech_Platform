"""Inline-клавиатуры клиентского бота."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.schemas.settings import AppSettings, Language

CONSENT_ACCEPT = "consent:accept"
CONSENT_DECLINE = "consent:decline"
LANGUAGE_PREFIX = "lang:"
ERASE_CONFIRM = "erase:confirm"
ERASE_CANCEL = "erase:cancel"
OFFER_HUMAN = "offer:human"
OFFER_NO = "offer:no"
LANGUAGE_LABELS: dict[Language, str] = {"ru": "Русский", "uz": "O'zbekcha", "en": "English"}


def consent(settings: AppSettings, language: Language) -> InlineKeyboardMarkup:
    texts = settings.texts
    row = [
        InlineKeyboardButton(text=texts.consent_button.get(language), callback_data=CONSENT_ACCEPT),
        InlineKeyboardButton(
            text=texts.consent_decline_button.get(language), callback_data=CONSENT_DECLINE
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def languages() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=label, callback_data=f"{LANGUAGE_PREFIX}{code}")
        for code, label in LANGUAGE_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def erase_confirm(settings: AppSettings, language: Language) -> InlineKeyboardMarkup:
    texts = settings.texts
    row = [
        InlineKeyboardButton(text=texts.erase_button.get(language), callback_data=ERASE_CONFIRM),
        InlineKeyboardButton(text=texts.cancel_button.get(language), callback_data=ERASE_CANCEL),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def handoff_offer(settings: AppSettings, language: Language) -> InlineKeyboardMarkup:
    """Под ответом «уточню у коллег»: передачу решает лид кнопкой, а не модель по тексту."""
    texts = settings.texts
    row = [
        InlineKeyboardButton(text=texts.handoff_offer_yes.get(language), callback_data=OFFER_HUMAN),
        InlineKeyboardButton(text=texts.handoff_offer_no.get(language), callback_data=OFFER_NO),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])
