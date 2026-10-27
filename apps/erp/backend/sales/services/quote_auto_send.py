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
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import transaction

logger = logging.getLogger(__name__)

CHANNEL_ORDER = ("telegram", "cabinet", "email")


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
        except ValueError as exc:
            report["error"] = str(exc)[:64] or "SEND_FAILED"
            logger.info("КП #%s: автоотправка остановлена гейтом %s", quote.pk, report["error"])
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
    return report


def _title(report: dict[str, Any]) -> str:
    if report["sent_via"]:
        return "КП отправлено клиенту после одобрения директором"
    return "КП не отправлено автоматически — отправит менеджер заявки"


def _detail(report: dict[str, Any]) -> str:
    parts = []
    if report["sent_via"]:
        parts.append("Каналы: " + ", ".join(report["sent_via"]))
    if report["skipped"]:
        parts.append("Недоступно: " + ", ".join(f"{s['channel']} ({s['reason']})" for s in report["skipped"]))
    if report["error"]:
        parts.append(f"Отправка остановлена: {report['error']}")
    return "; ".join(parts) or "Каналы не выбраны"
