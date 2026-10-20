"""Тексты бота по событиям ERP (FIX-34, I-8): из `settings.texts`, на языке лида, с кнопками.

Чистые функции без I/O: события ERP (`services/erp_events.py`) отдают сюда тип события и
payload, настройки приходят параметром. Идентификаторы клиента и сделки здесь не выбираются —
получателя определяет код обработчика.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.domain.urls import is_http_url
from app.schemas.settings import TextsSettings
from app.schemas.settings_base import LANGUAGES, Language

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
    labels = texts.erp_delivery_statuses.get(language).split("|")
    if status in DELIVERY_STATUSES:
        index = DELIVERY_STATUSES.index(status)
        if index < len(labels) and labels[index].strip():
            return labels[index].strip()
    return status


def _s(value: object) -> str:
    return "" if value is None else str(value)


def client_message(
    event: str,
    payload: Mapping[str, Any],
    *,
    deal_title: str,
    texts: TextsSettings,
    language: Language,
    cabinet_url: str,
) -> BotMessage | None:
    """Сообщение клиенту по событию ERP или `None`, если по этому событию бот молчит."""
    p = payload
    doc_button: tuple[str, str] | None = None
    if event == "quote.sent":
        text = texts.erp_quote_sent.get(language, deal=deal_title)
        url = p.get("public_url")
        if is_http_url(url):
            doc_button = (texts.erp_btn_quote.get(language), str(url))
    elif event == "invoice.issued":
        text = texts.erp_invoice_issued.get(
            language,
            number=_s(p.get("number")),
            amount=_s(p.get("amount")),
            currency=_s(p.get("currency")),
            due=_s(p.get("due_date")),
        )
        url = p.get("link")
        if is_http_url(url):
            doc_button = (texts.erp_btn_invoice.get(language), str(url))
    elif event == "invoice.paid":
        text = texts.erp_invoice_paid.get(
            language,
            number=_s(p.get("number")),
            amount=_s(p.get("amount")),
            currency=_s(p.get("currency")),
        )
    elif event == "delivery.status_changed":
        text = texts.erp_delivery_status.get(
            language,
            deal=deal_title,
            summary=_s(p.get("line_summary")),
            status=_delivery_status(texts, language, _s(p.get("status"))),
        )
    elif event == "delivery.eta_changed":
        text = texts.erp_delivery_eta_changed.get(
            language, deal=deal_title, summary=_s(p.get("line_summary")), eta=_s(p.get("eta"))
        )
    elif event == "act.issued":
        text = texts.erp_act_issued.get(language, number=_s(p.get("number")))
    else:
        return None
    buttons = [doc_button] if doc_button else []
    if is_http_url(cabinet_url):
        buttons.append((texts.erp_btn_cabinet.get(language), cabinet_url))
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
        return texts.erp_staff_quote_accepted.get(
            "ru", client=client_name, quote=_s(p.get("erp_quote_id")), deal=deal_title
        )
    if event == "act.returned":
        return texts.erp_staff_act_returned.get(
            "ru", number=_s(p.get("number")), deal=deal_title, reason=_s(p.get("reason"))
        )
    return None
