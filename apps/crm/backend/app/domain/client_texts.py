"""Тексты клиенту — один файл на трёх языках (SPEC-v3 §8, D1-9): подтверждение запроса с сайта, «Заявка принята»,
приглашение в кабинет и ответы бота на `/start`. Узбекский — латиница (`oʻ`, `gʻ`).

Без внутренних терминов: клиент не видит «лид», «сделка», коды и номера CRM. Чистые функции:
возвращают готовый текст
(бот) или тему и тело (письмо); получатель, канал и повторы — в `services/client_notices.py`.
Подписи кнопок — отсюда же.
Тексты, которые админ правит в «Настройках» (приветствие, согласие), остаются в `settings.texts`;
здесь — то, что отправляют
процессы D1-9, а не диалог бота.
"""

from dataclasses import dataclass
from typing import Final

LANGUAGES: Final = ("ru", "uz", "en")


@dataclass(frozen=True, slots=True)
class Mail:
    subject: str
    body: str


def lang(code: str | None) -> str:
    return code if code in LANGUAGES else "ru"


def _pick(table: dict[str, str], language: str | None) -> str:
    return table[lang(language)]


def _greet(language: str, name: str) -> str:
    clean = " ".join((name or "").split())
    table = {
        "ru": f"Здравствуйте, {clean}!" if clean else "Здравствуйте!",
        "uz": f"Assalomu alaykum, {clean}!" if clean else "Assalomu alaykum!",
        "en": f"Hello, {clean}!" if clean else "Hello!",
    }
    return table[language]


# ── Подтверждение запроса с сайта ────────────────────────────────────────────────────────────────

_CONFIRM_LEAD: Final = {
    "ru": "Мы получили ваш запрос и скоро свяжемся с вами. Обычно отвечаем в течение рабочего дня.",
    "uz": "Soʻrovingizni qabul qildik va tez orada siz bilan bogʻlanamiz. Odatda ish kuni davomida javob beramiz.",
    "en": "We have received your request and will get back to you shortly. We usually reply within a business day.",
}
_CONFIRM_SUBJECT: Final = {
    "ru": "Мы получили ваш запрос",
    "uz": "Soʻrovingizni qabul qildik",
    "en": "We have received your request",
}
_CONFIRM_BOT: Final = {
    "ru": "Удобнее общаться в Telegram? Откройте нашего бота — вся переписка будет в одном месте:",
    "uz": "Telegramda qulayroqmi? Botimizni oching — barcha yozishmalar bir joyda boʻladi:",
    "en": "Prefer Telegram? Open our bot and keep the whole conversation in one place:",
}


def web_confirmation_bot(language: str | None, name: str) -> str:
    """Сообщение в Telegram, если у запроса с сайта уже есть чат с ботом."""
    code = lang(language)
    return f"{_greet(code, name)}\n\n{_pick(_CONFIRM_LEAD, code)}"


def web_confirmation_mail(
    language: str | None, name: str, company: str, bot_link: str | None
) -> Mail:
    """Письмо-подтверждение без цитаты запроса (на указанный адрес его может написать кто угодно: письмо не
    должно пересылать чужой текст); ссылка на бота — подписанная, выдана системой (`start_link.issue_lead_link`)."""
    code = lang(language)
    parts = [_greet(code, name), _pick(_CONFIRM_LEAD, code)]
    if bot_link:
        parts.append(f"{_pick(_CONFIRM_BOT, code)}\n{bot_link}")
    parts.append(f"— {company}" if company else "")
    return Mail(_pick(_CONFIRM_SUBJECT, code), "\n\n".join(p for p in parts if p) + "\n")


# ── «Заявка принята, считаем» ────────────────────────────────────────────────────────────────────

_ACCEPTED_BOT: Final = {
    "ru": "Заявка{n} принята, считаем. Как только расчёт будет готов, напишем сюда.",
    "uz": "Ariza{n} qabul qilindi, hisoblaymiz. Hisob-kitob tayyor boʻlishi bilan shu yerga yozamiz.",
    "en": "Request{n} is accepted and we are working on it. We will write here as soon as the quote is ready.",
}
_ACCEPTED_SUBJECT: Final = {
    "ru": "Заявка{n} принята",
    "uz": "Ariza{n} qabul qilindi",
    "en": "Request{n} is accepted",
}
_ACCEPTED_MAIL_CABINET: Final = {
    "ru": "Статус заявки и все документы — в личном кабинете:",
    "uz": "Ariza holati va barcha hujjatlar shaxsiy kabinetda:",
    "en": "The status of your request and all documents are in your personal account:",
}
_OPEN_CABINET: Final = {"ru": "Открыть кабинет", "uz": "Kabinetni ochish", "en": "Open account"}


def open_cabinet_label(language: str | None) -> str:
    return _pick(_OPEN_CABINET, language)


def _n(number: str) -> str:
    clean = " ".join((number or "").split())
    return f" {clean}" if clean else ""


def request_accepted_bot(language: str | None, number: str) -> str:
    return _pick(_ACCEPTED_BOT, language).format(n=_n(number))


def request_accepted_mail(language: str | None, name: str, number: str, cabinet_url: str) -> Mail:
    code = lang(language)
    lines = [_greet(code, name), _pick(_ACCEPTED_BOT, code).format(n=_n(number))]
    if cabinet_url:
        lines.append(f"{_pick(_ACCEPTED_MAIL_CABINET, code)}\n{cabinet_url}")
    return Mail(_pick(_ACCEPTED_SUBJECT, code).format(n=_n(number)), "\n\n".join(lines) + "\n")


# ── Приглашение в кабинет через Telegram ────────────────────────────────────────────────────────

_INVITE_BOT: Final = {
    "ru": (
        "{greeting}\n\nВас пригласили в личный кабинет «{company}»: заявки, коммерческие предложения, договоры и счета — "
        "в одном месте. Нажмите кнопку ниже, вход — по вашему аккаунту Telegram."
    ),
    "uz": (
        "{greeting}\n\nSiz «{company}» shaxsiy kabinetiga taklif qilindingiz: arizalar, tijoriy takliflar, shartnomalar va "
        "hisob-fakturalar bir joyda. Quyidagi tugmani bosing — kirish Telegram akkauntingiz orqali."
    ),
    "en": (
        "{greeting}\n\nYou have been invited to the “{company}” personal account: requests, quotes, contracts and invoices "
        "in one place. Tap the button below — you sign in with your Telegram account."
    ),
}


def invite_bot(language: str | None, name: str, company: str) -> str:
    code = lang(language)
    return _pick(_INVITE_BOT, code).format(
        greeting=_greet(code, name), company=company or "RailTech"
    )


# ── Ответы бота на `/start` ─────────────────────────────────────────────────────────────────────

_START_DEAL: Final = {
    "ru": "Вижу вашу заявку{title}. Напишите, что хотите уточнить, — передам менеджеру.",
    "uz": "Arizangizni koʻrdim{title}. Nimani aniqlashtirmoqchi ekaningizni yozing — menejerga uzataman.",
    "en": "I can see your request{title}. Tell me what you would like to clarify and I will pass it to your manager.",
}
_START_LEAD_BOUND: Final = {
    "ru": "Готово: ваш запрос с сайта связан с этим чатом. Менеджер ответит здесь.",
    "uz": "Tayyor: saytdagi soʻrovingiz shu chat bilan bogʻlandi. Menejer shu yerda javob beradi.",
    "en": "Done: your request from the website is now linked to this chat. Your manager will reply here.",
}
_START_LINK_STALE: Final = {
    "ru": "Эта ссылка устарела или уже использована. Просто напишите нам здесь — поможем.",
    "uz": "Bu havola eskirgan yoki allaqachon ishlatilgan. Shu yerga yozing — yordam beramiz.",
    "en": "This link has expired or has already been used. Just write to us here and we will help.",
}


def start_deal(language: str | None, title: str | None) -> str:
    clean = " ".join((title or "").split())
    return _pick(_START_DEAL, language).format(title=f" «{clean}»" if clean else "")


def start_lead_bound(language: str | None) -> str:
    return _pick(_START_LEAD_BOUND, language)


def start_link_stale(language: str | None) -> str:
    return _pick(_START_LINK_STALE, language)
