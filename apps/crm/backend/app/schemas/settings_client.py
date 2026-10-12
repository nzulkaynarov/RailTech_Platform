"""Тексты клиентского меню бота и запроса номера телефона (Q-011, Q-020).

Часть ключа `texts` (`TextsSettings` наследует этот класс): вынесены, чтобы
`settings.py` оставался в лимите размера файла. Узбекский — латиница oʻ/gʻ.
"""

from app.schemas.settings_base import CheckedTexts, LocalizedText
from app.schemas.settings_base import localized as _t


class ClientBotTexts(CheckedTexts):
    # Подписи команд в кнопке «Меню» Telegram (до 256 символов, без эмодзи).
    menu_start: LocalizedText = _t("Начать", "Boshlash", "Start")
    menu_human: LocalizedText = _t(
        "Связаться с менеджером", "Menejer bilan bogʻlanish", "Talk to a manager"
    )
    menu_lang: LocalizedText = _t("Сменить язык", "Tilni oʻzgartirish", "Change language")
    menu_help: LocalizedText = _t("Что умеет бот", "Bot nimalar qila oladi", "What the bot can do")
    menu_delete: LocalizedText = _t(
        "Удалить переписку", "Yozishmani oʻchirish", "Delete the conversation"
    )
    menu_docs: LocalizedText = _t("Мои документы", "Hujjatlarim", "My documents")
    menu_request: LocalizedText = _t("Запрос менеджеру", "Menejerga soʻrov", "Request to a manager")
    menu_status: LocalizedText = _t("Статус запроса", "Soʻrov holati", "Request status")
    client_only: LocalizedText = _t(
        "Эта команда доступна клиентам компании после заключения договора. Пока я могу ответить на ваши вопросы или связать вас с менеджером — /human.",
        "Bu buyruq shartnoma tuzilgandan soʻng kompaniya mijozlari uchun mavjud. Hozircha savollaringizga javob berishim yoki sizni menejer bilan bogʻlashim mumkin — /human.",
        "This command is available to company clients once a contract is signed. For now I can answer your questions or connect you with a manager — /human.",
    )
    docs_list: LocalizedText = _t(
        "Ваши документы — нажмите, чтобы получить файл:",
        "Hujjatlaringiz — faylni olish uchun bosing:",
        "Your documents — tap one to get the file:",
    )
    docs_empty: LocalizedText = _t(
        "Пока у вас нет документов в системе. Если документ нужен — напишите /request.",
        "Hozircha tizimda hujjatlaringiz yoʻq. Hujjat kerak boʻlsa — /request yozing.",
        "There are no documents for you yet. If you need one, send /request.",
    )
    request_prompt: LocalizedText = _t(
        "Опишите ваш запрос одним сообщением — я передам его менеджеру.",
        "Soʻrovingizni bitta xabarda yozing — uni menejerga yuboraman.",
        "Describe your request in one message and I'll pass it to a manager.",
    )
    # {number} — номер запроса в CRM.
    request_created: LocalizedText = _t(
        "Запрос №{number} передан менеджеру. Статус — /status.",
        "№{number} soʻrov menejerga yuborildi. Holati — /status.",
        "Request #{number} has been passed to a manager. Status — /status.",
    )
    request_status_open: LocalizedText = _t(
        "Запрос №{number} от {date} в работе у менеджера: «{summary}».",
        "{date} dagi №{number} soʻrov menejer koʻrib chiqmoqda: «{summary}».",
        "Request #{number} from {date} is being handled by a manager: “{summary}”.",
    )
    request_status_none: LocalizedText = _t(
        "Открытых запросов нет. Новый запрос — /request.",
        "Ochiq soʻrovlar yoʻq. Yangi soʻrov — /request.",
        "You have no open requests. New request — /request.",
    )
    phone_request: LocalizedText = _t(
        "Чтобы менеджер мог при необходимости позвонить, поделитесь номером телефона кнопкой ниже. Это необязательно.",
        "Menejer kerak boʻlsa qoʻngʻiroq qila olishi uchun quyidagi tugma orqali telefon raqamingizni yuboring. Bu majburiy emas.",
        "So a manager can call you if needed, share your phone number with the button below. This is optional.",
    )
    phone_share_button: LocalizedText = _t(
        "Поделиться номером", "Raqamni yuborish", "Share my number"
    )
    phone_skip_button: LocalizedText = _t("Не сейчас", "Hozir emas", "Not now")
    phone_saved: LocalizedText = _t(
        "Спасибо, номер сохранён.", "Rahmat, raqam saqlandi.", "Thank you, your number is saved."
    )
    phone_skipped: LocalizedText = _t(
        "Хорошо, продолжаем без номера.",
        "Yaxshi, raqamsiz davom etamiz.",
        "Okay, we'll continue without it.",
    )
    phone_not_own: LocalizedText = _t(
        "Сохранить можно только ваш собственный номер — кнопкой «Поделиться номером».",
        "Faqat oʻz raqamingizni «Raqamni yuborish» tugmasi orqali saqlash mumkin.",
        "Only your own number can be saved — use the “Share my number” button.",
    )
