"""Автоотправка КП клиенту после одобрения директором по выбранным каналам (ERP-11, решение архитектора 2026-10-28).

Директор одобряет КП в EDS с каналами (`eds.approval.decided`, `channels`): ERP сама отправляет КП клиенту по тем из них,
что доступны, в транзакции применения решения. Доступность каждого канала проверяет сервер:

* `email` — у КП есть получатель письма (`resolve_quote_recipient`: представитель клиента или контакт сделки с e-mail);
* `telegram` — контакт сделки (или основной контакт компании) с Telegram и клиент, переданный из CRM (бот CRM пишет по
  событию `quote.sent`; ERP в Telegram не пишет);
* `cabinet` — у компании есть контакт, приглашённый в кабинет или уже входивший (не в архиве).

Недоступный канал не роняет одобрение: он попадает в итог (`Quote.send_report.skipped` с причиной) и в журнал КП.
Нет ни одного доступного канала или отправку остановил гейт (`QUOTE_BELOW_COST`, `FX_RATE_MISSING`…) — КП остаётся
«Готово к отправке», и его отправляет менеджер заявки через `quote.send` (C1-G-4). Одобрение без каналов автоотправку не
запускает. Повтор события решение не применяет повторно (`apply_director_decision` — `duplicate`), второй отправки нет.

D17G-2 (гейт D1-7): те же проверки отдают доступность всех трёх каналов заранее (`channel_availability` — панель одобрения
и карточка КП в Платформе), а `deliver` отправляет КП по одному каналу из карточки КП: менеджер заявки или директор
(`quote.send`), когда канал не сработал или не был выбран. Уведомление менеджеру — с причиной словами, не кодом.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import transaction

logger = logging.getLogger(__name__)

CHANNEL_ORDER = ("telegram", "cabinet", "email")
# Каналы, по которым КП можно отправить из карточки (`deliver`). Кабинет не «отправляется»: отправленное КП клиент видит в
# кабинете всегда (DECISIONS 2026-10-28 «ERP-11»), а без приглашения его открыть некому — это приглашение, не отправка.
DELIVERABLE = ("telegram", "email")

CHANNEL_NAMES = {"telegram": "Telegram", "cabinet": "Кабинет", "email": "Почта"}
# Причины словами — для уведомления менеджеру и журнала КП. Коды остаются в `send_report`, интерфейс переводит их сам.
REASON_TEXT = {
    "CONTACT_EMAIL_REQUIRED": "у контакта клиента нет e-mail",
    "CONTACT_TELEGRAM_REQUIRED": "контакт клиента не подключён к Telegram-боту",
    "CLIENT_NOT_IN_CRM": "клиент не передан в CRM, бот его не знает",
    "CABINET_NOT_INVITED": "клиент не приглашён в кабинет",
    "EMAIL_DELIVERY_FAILED": "письмо не ушло",
    "smtp_not_configured": "почта не настроена (Настройки · Подключения · Почта)",
    "QUOTE_BELOW_COST": "цена ниже себестоимости",
    "FX_RATE_MISSING": "нет курса валюты",
    "QUOTE_HAS_UNPRICED_LINES": "есть позиции без цены",
    "BELOW_FLOOR_JUSTIFICATION_REQUIRED": "маржа ниже минимальной, нужно обоснование",
    "QUOTE_NOT_CLAIMED": "у КП нет компании-продавца",
    "RECIPIENT_REQUIRED": "некому отправить: у заявки нет контакта клиента",
    "SEND_FAILED": "сбой отправки",
    "UNKNOWN_CHANNEL": "незнакомый канал",
}


def _company_contacts(quote):
    company = quote.deal.company
    if company is None:
        return []
    return list(company.contacts.filter(archived_at__isnull=True))


def _telegram_reason(quote) -> Optional[str]:
    from integration.models import CrmClientMapping

    deal = quote.deal
    contact = deal.contact
    if contact is None:
        contacts = _company_contacts(quote)
        contact = next((c for c in contacts if c.is_primary), contacts[0] if contacts else None)
    if contact is None or not contact.telegram_user_id or contact.archived_at is not None:
        return "CONTACT_TELEGRAM_REQUIRED"
    if not CrmClientMapping.objects.filter(company_id=deal.company_id).exists():
        return "CLIENT_NOT_IN_CRM"
    return None


def _cabinet_reason(quote) -> Optional[str]:
    if any(c.invited_at or c.last_login_at for c in _company_contacts(quote)):
        return None
    return "CABINET_NOT_INVITED"


def _email_reason(quote) -> Optional[str]:
    from crm.services.quotes._shared import resolve_quote_recipient

    return None if resolve_quote_recipient(quote) is not None else "CONTACT_EMAIL_REQUIRED"


_CHECKS = {"telegram": _telegram_reason, "cabinet": _cabinet_reason, "email": _email_reason}


def reason_text(reason: str, detail: str = "") -> str:
    """Причина словами; у недоставленного письма — причина почтового сервиса, если она известна."""
    if reason == "EMAIL_DELIVERY_FAILED" and detail in REASON_TEXT:
        return REASON_TEXT[detail]
    return REASON_TEXT.get(reason, reason)


def _contact_name(quote) -> Optional[str]:
    """Кому уйдёт КП: контакт сделки, иначе основной контакт компании, иначе зарегистрированный покупатель."""
    deal = quote.deal
    contact = deal.contact
    if contact is None:
        contacts = _company_contacts(quote)
        contact = next((c for c in contacts if c.is_primary), contacts[0] if contacts else None)
    if contact is not None and contact.name:
        return contact.name
    client = deal.client
    if client is not None:
        return client.get_full_name() or client.email or None
    return None


def channel_availability(quote) -> dict[str, Any]:
    """Доступность каждого канала по фактическим контактам клиента — те же проверки, что у автоотправки (D17G-2).

    `{"contact_name": …, "channels": [{"channel", "available", "reason"}]}` в порядке `CHANNEL_ORDER`; `reason` — код
    `_CHECKS` (`CONTACT_EMAIL_REQUIRED`…) у недоступного канала, иначе `None`."""
    rows = []
    for channel in CHANNEL_ORDER:
        reason = _CHECKS[channel](quote)
        rows.append({"channel": channel, "available": reason is None, "reason": reason})
    return {"contact_name": _contact_name(quote), "channels": rows}


def check_channels(quote, channels: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Выбранные директором каналы → (доступные, пропущенные с причиной). Незнакомый канал — `UNKNOWN_CHANNEL`."""
    available: list[str] = []
    skipped: list[dict[str, str]] = []
    for channel in sorted(dict.fromkeys(channels), key=lambda c: CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else 99):
        check = _CHECKS.get(channel)
        reason = check(quote) if check else "UNKNOWN_CHANNEL"
        if reason is None:
            available.append(channel)
        else:
            skipped.append({"channel": channel, "reason": reason})
    return available, skipped


def _sender(quote, director):
    """От чьего имени отправка: директор (если сопоставлен с ERP), иначе менеджер заявки, иначе автор КП."""
    return director or quote.deal.manager or quote.prepared_by


def auto_send(quote, channels: list[str], *, director=None, outgoing_number: str = "") -> dict[str, Any]:
    """Отправить одобренное КП по доступным каналам; итог — в `quote.send_report` и в журнал. Вызывать в транзакции
    применения решения директора, КП — «Готово к отправке». Возвращает итог."""
    from crm.services import QuoteLifecycleService
    from crm.services.quotes._shared import _log_quote

    available, skipped = check_channels(quote, channels)
    report: dict[str, Any] = {"requested": list(channels), "sent_via": [], "skipped": skipped, "error": None}
    if available:
        justification = f"Одобрено директором {outgoing_number}".strip()[:500]
        try:
            with transaction.atomic():
                QuoteLifecycleService.send_to_client(
                    quote.pk, _sender(quote, director), justification=justification, channels=available
                )
            report["sent_via"] = available
        except ValueError as exc:  # гейт отправки (QUOTE_BELOW_COST, FX_RATE_MISSING…) — код как есть
            report["error"] = str(exc)[:64] or "SEND_FAILED"
            logger.info("КП #%s: автоотправка остановлена гейтом %s", quote.pk, report["error"])
        except Exception as exc:  # noqa: BLE001 — любой сбой отправки откатывает только точку сохранения
            report["error"], report["error_detail"] = "SEND_FAILED", f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("КП #%s: автоотправка упала, одобрение остаётся", quote.pk)
    quote.refresh_from_db()
    quote.send_report = report
    quote.save(update_fields=["send_report", "updated_at"])
    _log_quote(
        quote,
        director,
        _title(report),
        _detail(report),
        event_code="quote.auto_sent" if report["sent_via"] else "quote.auto_send_skipped",
        event_params={"number": quote.number or quote.pk, **report},
    )
    _notify_manager(quote, report)
    return report


def _unsent_channels(report: dict[str, Any]) -> list[str]:
    """Каналы, по которым КП не ушло: недоступные и все доступные, если отправку остановила ошибка."""
    failed = [] if report["sent_via"] else [c for c in report["requested"] if c not in _skipped(report)]
    return [*_skipped(report), *(failed if report["error"] else [])]


def _skipped(report: dict[str, Any]) -> list[str]:
    return [item["channel"] for item in report["skipped"]]


def _notify_manager(quote, report: dict[str, Any]) -> None:
    """Колокольчик менеджеру заявки (`deal.manager`, иначе автору КП): по каким каналам КП не ушло и почему."""
    unsent = _unsent_channels(report)
    if not unsent:
        return
    reasons = {item["channel"]: item["reason"] for item in report["skipped"]}
    notify_unsent(
        quote,
        [(channel, reasons.get(channel) or report["error"] or "SEND_FAILED", "") for channel in unsent],
        error=report["error"] or "",
    )


def notify_unsent(quote, lines: list[tuple[str, str, str]], *, error: str = "") -> None:
    """Уведомление «КП не отправлено по каналу» с причиной словами и ссылкой на карточку КП (D17G-2).

    `lines` — (канал, код причины, деталь почтового сервиса). Ссылку на карточку КП в Платформе собирает BFF по коду
    события и номеру КП; `link` — прежняя ссылка старого фронта."""
    from crm.services.approvals import _link, _notify_user

    if not lines:
        return
    number = quote.number or quote.pk
    label = quote.number or f"КП #{quote.pk}"
    channels = ", ".join(channel for channel, _reason, _detail in lines)
    names = ", ".join(CHANNEL_NAMES.get(channel, channel) for channel, _reason, _detail in lines)
    why = "; ".join(
        f"{CHANNEL_NAMES.get(channel, channel)} — {reason_text(reason, detail)}" for channel, reason, detail in lines
    )
    _notify_user(
        quote.deal.manager_id or quote.prepared_by_id,
        f"{label}: не отправлено — {names}"[:200],
        f"{why}. Отчёт по каналам и отправка — в карточке КП.",
        type_code="WARNING",
        link=_link(quote),
        event_code="quote.auto_send_failed",
        event_params={
            "number": number,
            "channels": channels,
            "error": error,
            "reasons": {channel: (detail or reason) for channel, reason, detail in lines},
        },
    )


def _title(report: dict[str, Any]) -> str:
    if report["sent_via"]:
        return "КП отправлено клиенту после одобрения директором"
    return "КП не отправлено автоматически — отправит менеджер заявки"


def _detail(report: dict[str, Any]) -> str:
    parts = []
    if report["sent_via"]:
        parts.append("Каналы: " + ", ".join(report["sent_via"]))
    if report["skipped"]:
        parts.append(
            "Недоступно: "
            + ", ".join(
                f"{CHANNEL_NAMES.get(s['channel'], s['channel'])} ({reason_text(s['reason'])})"
                for s in report["skipped"]
            )
        )
    if report["error"]:
        parts.append(f"Отправка остановлена: {report['error']}")
    return "; ".join(parts) or "Каналы не выбраны"


def deliver(quote_id: int, channel: str, user) -> Any:
    """Отправить одобренное КП клиенту по одному каналу из карточки КП (D17G-2). Возвращает КП.

    Право — у вызывающего (`can_send_quote_to_client`). Канал проверяется теми же правилами, что при автоотправке;
    недоступный — `ValueError(<код причины>)`. КП «Готово к отправке» (каналы не выбраны, недоступны или отправку
    остановил гейт) уходит обычной отправкой `send_to_client` только по этому каналу. Уже отправленное КП — повтор по
    каналу: письмо ставится в очередь заново (итог вернёт почтовый сервис CRM), в Telegram — новое `quote.sent` с этим
    каналом (бот CRM пишет клиенту). Итог — в `send_report` и журнале КП.
    """
    from crm.constants import QuoteStatusCode
    from crm.models import Quote
    from crm.services import QuoteLifecycleService
    from crm.services.quotes._shared import _log_quote

    if channel not in DELIVERABLE:
        raise ValueError("UNKNOWN_CHANNEL")
    with transaction.atomic():
        quote = (
            Quote.objects.select_for_update(of=("self",))
            .select_related("deal__company", "deal__client", "deal__contact", "status")
            .get(pk=quote_id)
        )
        reason = _CHECKS[channel](quote)
        if reason is not None:
            raise ValueError(reason)
        current = quote.status.code if quote.status else ""
        if current == QuoteStatusCode.READY_TO_SEND:
            justification = f"Одобрено директором {quote.outgoing_number}".strip() if quote.outgoing_number else ""
            QuoteLifecycleService.send_to_client(quote.pk, user, justification=justification[:500], channels=[channel])
            quote.refresh_from_db()
        elif current == QuoteStatusCode.SENT:
            _redeliver(quote, channel)
        else:
            raise ValueError("INVALID_STATUS")
        quote.send_report = _delivered(quote.send_report, channel)
        quote.save(update_fields=["send_report", "updated_at"])
        name = CHANNEL_NAMES[channel]
        _log_quote(
            quote,
            user,
            f"КП отправлено клиенту вручную: {name}",
            f"Отправил {user.get_full_name() or user.email}" if user is not None else "",
            event_code="quote.delivered",
            event_params={"number": quote.number or quote.pk, "channel": channel},
        )
    return quote


def _redeliver(quote, channel: str) -> None:
    """Повтор уже отправленного КП по каналу: тот же номер, цены и публичная ссылка — только доставка."""
    if channel == "email":
        from crm.services.quotes._shared import resolve_quote_recipient
        from crm.tasks import send_quote_email

        if resolve_quote_recipient(quote) is None:
            raise ValueError("CONTACT_EMAIL_REQUIRED")
        quote_id = quote.pk
        transaction.on_commit(lambda: send_quote_email.delay(quote_id))
        return
    from integration.services import events

    events.publish_quote_sent(quote, channels=[channel])


def _delivered(report: Optional[dict[str, Any]], channel: str) -> dict[str, Any]:
    """Итог после ручной отправки: канал — в `sent_via`, его пропуск и ошибка отправки снимаются; у письма сбрасываются
    отметки прошлого итога, чтобы новый итог почтового сервиса применился (`notifications.mail_bus`)."""
    report = dict(report or {})
    requested = list(report.get("requested") or [])
    if channel not in requested:
        requested.append(channel)
    report["requested"] = requested
    report["sent_via"] = [*(c for c in report.get("sent_via") or [] if c != channel), channel]
    report["skipped"] = [s for s in report.get("skipped") or [] if s.get("channel") != channel]
    report["error"] = None
    report.pop("error_detail", None)
    if channel == "email":
        report.pop("email_sent_at", None)
        report.pop("email_failed_at", None)
    return report
