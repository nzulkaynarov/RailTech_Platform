"""Тексты бота по событиям ERP (FIX-34, I-8): из `settings.texts`, на языке лида, с кнопками.

Чистые функции без I/O: события ERP (`services/erp_events.py`) отдают сюда тип события и
payload, настройки приходят параметром. Идентификаторы клиента и сделки здесь не выбираются —
получателя определяет код обработчика.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.domain import client_texts
from app.domain.urls import is_http_url
from app.schemas.settings import TextsSettings
from app.schemas.settings_base import LANGUAGES, Language, LocalizedText

# Порядок статусов поставки = порядок подписей в `texts.erp_delivery_statuses` (контракт событий).
DELIVERY_STATUSES: Final = ("assembling", "in_transit", "ready_to_ship", "shipped", "delivered")


@dataclass(frozen=True, slots=True)
class BotMessage:
    text: str
    # (подпись, адрес) — каждая кнопка в своей строке под сообщением.
    buttons: tuple[tuple[str, str], ...] = ()


def pick_language(raw: str | None) -> Language:
    """Язык лида; неизвестный — русский (как у остальных уведомлений бота)."""
    for language in LANGUAGES:
        if raw == language:
            return language
    return "ru"


def _delivery_status(texts: TextsSettings, language: Language, status: str) -> str:
    labels = _text(texts, "erp_delivery_statuses", language).split("|")
    if status in DELIVERY_STATUSES:
        index = DELIVERY_STATUSES.index(status)
        if index < len(labels) and labels[index].strip():
            return labels[index].strip()
    return status


def _text(texts: TextsSettings, name: str, language: Language, **params: str) -> str:
    """Текст из настроек; пустой (админ стёр) — по умолчанию: пустое сообщение Telegram отклонит."""
    value: LocalizedText = getattr(texts, name)
    if not value.get(language).strip():
        default = TextsSettings.model_fields[name].default
        value = default if isinstance(default, LocalizedText) else value
    return value.get(language, **params)


def _s(value: object) -> str:
    return "" if value is None else str(value)


def acceptance_code_message(
    *,
    code: str,
    minutes: int,
    deal_title: str,
    texts: TextsSettings,
    language: Language,
) -> BotMessage:
    """Код акцепта КП контакту (шов 0.3.0, Q-FIX22-1): текст из `settings.texts`, без кнопок.

    Код подставляется только здесь, в момент отправки; в `BotMessage` он живёт до `send_message`
    и нигде не сохраняется (ни в журнале событий, ни в `outbox`).
    """
    text = _text(
        texts,
        "erp_quote_acceptance_code",
        language,
        deal=deal_title,
        code=code,
        minutes=str(minutes),
    )
    return BotMessage(text)


def _telegram_chosen(payload: Mapping[str, Any]) -> bool:
    """`quote.sent.channels` (ERP-11): нет списка — отправка менеджером, все каналы клиента; есть —
    только выбранные."""
    channels = payload.get("channels")
    return channels is None or "telegram" in channels


#: Источники заявки, о которых клиенту пишем «принята»: заявку завёл менеджер из лида (`crm`) или
#: сам
#: клиент в кабинете (`cabinet`). Заявка сотрудника в ERP (`erp`) клиенту не сообщается.
ACCEPTED_SOURCES: Final = ("crm", "cabinet")


def request_accepted(
    payload: Mapping[str, Any], *, number: str, language: Language, cabinet_url: str
) -> BotMessage | None:
    """«Заявка ЗВ-… принята, считаем» + «Открыть кабинет» (SPEC-v3 §3.1 шаг 2, Приложение Б).

    Тексты — `domain/client_texts.py`, без внутренних терминов. `None` — по этому источнику
    клиенту не пишем."""
    if payload.get("source") not in ACCEPTED_SOURCES:
        return None
    text = client_texts.request_accepted_bot(language, number)
    buttons = (
        ((client_texts.open_cabinet_label(language), cabinet_url),)
        if is_http_url(cabinet_url)
        else ()
    )
    return BotMessage(text, buttons)


# Страницы кабинета (`apps/cabinet/src/app/routes.tsx`) по событию: счёт и акт — раздел со строкой
# объекта (`?focus=`), поставка — проект.
_CABINET_FOCUS: Final = {
    "invoice.issued": ("/invoices", "erp_invoice_id"),
    "invoice.paid": ("/invoices", "erp_invoice_id"),
    "act.issued": ("/acts", "erp_act_id"),
}
_DELIVERY_EVENTS: Final = frozenset({"delivery.status_changed", "delivery.eta_changed"})
_LEGACY_INVOICE_LINK: Final = re.compile(r"^(https?://[^?#]+)/invoices/(\d+)$")


def cabinet_target(
    event: str, payload: Mapping[str, Any], cabinet_url: str, erp_deal_id: int | None
) -> str:
    """Куда ведёт кнопка «Открыть кабинет»: страница самого объекта события, а не главная.

    Адрес кабинета берётся из настроек компании; нет id объекта (старое событие) — главная."""
    if not is_http_url(cabinet_url):
        return cabinet_url
    base = cabinet_url.rstrip("/")
    focus = _CABINET_FOCUS.get(event)
    if focus is not None and isinstance(payload.get(focus[1]), int):
        return f"{base}{focus[0]}?focus={payload[focus[1]]}"
    if event in _DELIVERY_EVENTS and erp_deal_id:
        return f"{base}/deals/{erp_deal_id}"
    return cabinet_url


def _invoice_link(url: object) -> str:
    """`…/invoices/<id>` (адрес прежних событий) в кабинете нет — это `/invoices?focus=<id>`."""
    match = _LEGACY_INVOICE_LINK.match(str(url))
    return f"{match.group(1)}/invoices?focus={match.group(2)}" if match else str(url)


def client_message(
    event: str,
    payload: Mapping[str, Any],
    *,
    deal_title: str,
    texts: TextsSettings,
    language: Language,
    cabinet_url: str,
    deal_number: str = "",
    erp_deal_id: int | None = None,
) -> BotMessage | None:
    """Сообщение клиенту по событию ERP или `None`, если по этому событию бот молчит."""
    p = payload
    if event == "quote.sent" and not _telegram_chosen(p):
        return None  # ERP-11: директор выбрал каналы без Telegram — клиенту в бот КП не шлём
    doc_button: tuple[str, str] | None = None
    if event == "request.created":
        return request_accepted(p, number=deal_number, language=language, cabinet_url=cabinet_url)
    if event == "quote.sent":
        text = _text(texts, "erp_quote_sent", language, deal=deal_title)
        url = p.get("public_url")
        if is_http_url(url):
            doc_button = (_text(texts, "erp_btn_quote", language), str(url))
    elif event == "invoice.issued":
        text = _text(
            texts,
            "erp_invoice_issued",
            language,
            number=_s(p.get("number")),
            amount=_s(p.get("amount")),
            currency=_s(p.get("currency")),
            due=_s(p.get("due_date")),
        )
        url = p.get("link")
        if is_http_url(url):
            doc_button = (_text(texts, "erp_btn_invoice", language), _invoice_link(url))
    elif event == "invoice.paid":
        text = _text(
            texts,
            "erp_invoice_paid",
            language,
            number=_s(p.get("number")),
            amount=_s(p.get("amount")),
            currency=_s(p.get("currency")),
        )
    elif event == "delivery.status_changed":
        text = _text(
            texts,
            "erp_delivery_status",
            language,
            deal=deal_title,
            summary=_s(p.get("line_summary")),
            status=_delivery_status(texts, language, _s(p.get("status"))),
        )
    elif event == "delivery.eta_changed":
        text = _text(
            texts,
            "erp_delivery_eta_changed",
            language,
            deal=deal_title,
            summary=_s(p.get("line_summary")),
            eta=_s(p.get("eta")),
        )
    elif event == "act.issued":
        text = _text(texts, "erp_act_issued", language, number=_s(p.get("number")))
    else:
        return None
    buttons = [doc_button] if doc_button else []
    if is_http_url(cabinet_url):
        target = cabinet_target(event, p, cabinet_url, erp_deal_id)
        buttons.append((_text(texts, "erp_btn_cabinet", language), target))
    return BotMessage(text, tuple(buttons))


def staff_alert(
    event: str,
    payload: Mapping[str, Any],
    *,
    client_name: str,
    deal_title: str,
    texts: TextsSettings,
) -> str | None:
    """Личное сообщение ответственному сотруднику (интерфейс команды — русский)."""
    p = payload
    if event == "quote.accepted":
        return _text(
            texts,
            "erp_staff_quote_accepted",
            "ru",
            client=client_name,
            quote=_s(p.get("erp_quote_id")),
            deal=deal_title,
        )
    if event == "act.returned":
        return _text(
            texts,
            "erp_staff_act_returned",
            "ru",
            number=_s(p.get("number")),
            deal=deal_title,
            reason=_s(p.get("reason")),
        )
    if event == "delivery.line_disputed":
        return _text(
            texts,
            "erp_staff_delivery_line_disputed",
            "ru",
            client=client_name,
            line=_s(p.get("line_no")),
            title=_s(p.get("title")),
            deal=deal_title,
            remark=_s(p.get("remark")),
        )
    return None


def feed_note(
    event: str,
    payload: Mapping[str, Any],
    *,
    contact_name: str | None,
    deal_title: str,
    texts: TextsSettings,
) -> str | None:
    """Запись в ленту лида по приёмке или замечанию к строке поставки (FIX-37); иначе `None`.

    Лента — интерфейс команды, поэтому текст русский. Имя контакта — `actor.name` события;
    без имени пишем «контакт клиента», а не пустые скобки.
    """
    names = {
        "delivery.line_accepted": "erp_note_delivery_line_accepted",
        "delivery.line_disputed": "erp_note_delivery_line_disputed",
    }
    if event not in names:
        return None
    return _text(
        texts,
        names[event],
        "ru",
        contact=(contact_name or "").strip() or "контакт клиента",
        line=_s(payload.get("line_no")),
        title=_s(payload.get("title")),
        deal=deal_title,
        remark=_s(payload.get("remark")),
    )
