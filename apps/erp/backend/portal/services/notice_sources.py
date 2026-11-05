"""Источники уведомлений кабинета: события ERP для контрагента → колокольчик и внешний канал (NOTIFY-2).

Вызываются публикаторами событий (`integration/services/events.py`) в той же транзакции, что и событие шины, — поэтому
уведомление есть ровно тогда, когда есть событие (откат — нет ни того, ни другого), и в том числе у компании, не
сопоставленной клиенту CRM (события на шине у неё нет, бот ей не пишет — маршрутизатор шлёт письмо). Ключ события
(`dedup`) делает повтор идемпотентным: переотправка того же КП, повторная публикация статуса не дают второй строки.
"""

from __future__ import annotations

from typing import Optional

from django.utils import timezone
from portal import projections

from .notices import notify


def _deal_ref(deal) -> str:
    return projections.deal_number(deal) if deal is not None else ""


def _document_contacts(deal) -> tuple[int, ...]:
    """Контакт документа — контакт сделки: ему письмо-уведомление и без приглашения в кабинет (решение лида по #402)."""
    contact_id = getattr(deal, "contact_id", None) if deal is not None else None
    return (contact_id,) if isinstance(contact_id, int) else ()


def _legacy_buyer_emails(deal) -> set[str]:
    """Адреса пользователей ERP компании-покупателя, которым письмо о счёте, акте и просрочке уже шлёт `deal_emails`
    (членство B2B; у клиентов портала его нет) — контакту с тем же адресом второе письмо не нужно."""
    from crm.services.deal_emails import _emails_for
    from crm.services.deal_notifications import buyer_team_user_ids

    return {email for email, _user_id in _emails_for(buyer_team_user_ids(deal))}


def quote_sent(quote, channels: Optional[list[str]] = None, bot_reaches: Optional[bool] = None) -> None:
    """КП отправлено клиенту — ждёт решения. Письмо с КП уже уходит получателю КП (каналы ERP-11): ему второго не шлём;
    бот пишет, если среди каналов есть Telegram (нет списка — все каналы)."""
    from crm.services.quotes import resolve_quote_recipient

    deal = quote.deal
    emailed: set[str] = set()
    if channels is None or "email" in channels:
        recipient = resolve_quote_recipient(quote)
        if recipient:
            emailed.add(recipient[0])
    if channels is not None and "telegram" not in channels:
        bot_reaches = False
    number = projections.quote_number(quote)
    notify(
        "quote_sent",
        company=deal.company,
        object_id=quote.pk,
        object_number=number,
        params={"number": number, "deal": _deal_ref(deal)},
        link=f"/quotes/{quote.pk}",
        dedup=f"{quote.pk}:v{quote.version}",
        bot_reaches=bot_reaches,
        already_emailed=emailed,
        document_contact_ids=_document_contacts(deal),
    )


def _currency(invoice) -> str:
    """Код валюты счёта — как в событии `invoice.*` (`events.publish_invoice_event`): справочник или строка, нет — UZS."""
    currency = getattr(invoice, "currency", None)
    return (getattr(currency, "code", None) or (str(currency) if currency else "UZS")).upper()


def invoice_issued(invoice, bot_reaches: Optional[bool] = None) -> None:
    deal = invoice.deal
    number = invoice.number or f"INV-{invoice.pk}"
    notify(
        "invoice_issued",
        company=deal.company,
        object_id=invoice.pk,
        object_number=number,
        params={
            "number": number,
            **projections.money(invoice.total_incl_vat, _currency(invoice)),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else "",
        },
        link=f"/invoices?focus={invoice.pk}",
        dedup=f"{invoice.pk}",
        bot_reaches=bot_reaches,
        already_emailed=_legacy_buyer_emails(deal),
        document_contact_ids=_document_contacts(deal),
    )


def payment_overdue(invoice, bot_reaches: Optional[bool] = None) -> None:
    deal = invoice.deal
    number = invoice.number or f"INV-{invoice.pk}"
    notify(
        "payment_overdue",
        company=deal.company,
        object_id=invoice.pk,
        object_number=number,
        params={
            "number": number,
            **projections.money(invoice.balance_due, _currency(invoice)),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else "",
        },
        link=f"/invoices?focus={invoice.pk}",
        dedup=f"{invoice.pk}:{invoice.due_date.isoformat() if invoice.due_date else ''}",
        bot_reaches=bot_reaches,
        already_emailed=_legacy_buyer_emails(deal),
        document_contact_ids=_document_contacts(deal),
    )


def act_issued(act, bot_reaches: Optional[bool] = None, *, reminder: bool = False) -> None:
    """Акт выставлен (или выставлен заново после возврата) и ждёт приёмки; `reminder` — напоминание исполнителя: новая
    строка ленты и письмо (бот о напоминании не пишет — событие шины не публикуется)."""
    deal = act.deal
    number = act.number or f"ACT-{act.pk}"
    if reminder:
        stamp = f"remind:{act.reminder_sent_at.isoformat() if act.reminder_sent_at else ''}"
        bot_reaches = False
    else:
        stamp = act.issuer_signed_at.isoformat() if act.issuer_signed_at else str(act.issued_at or "")
    notify(
        "act_issued",
        company=deal.company,
        object_id=act.pk,
        object_number=number,
        params={"number": number, "reminder": "1" if reminder else ""},
        link=f"/acts?focus={act.pk}",
        dedup=f"{act.pk}:{stamp}",
        bot_reaches=bot_reaches,
        already_emailed=_legacy_buyer_emails(deal),
        document_contact_ids=_document_contacts(deal),
    )


#: Статусы поставки, о которых сообщаем контрагенту: решения самого клиента (принято, оспорено) ему не повторяем.
CLIENT_DECISION_STATUSES = ("ACCEPTED", "DISPUTED")


def _change_stamp(fulfillment) -> str:
    """Порядок изменения поставки: время сохранения строки исполнения в транзакции события. Повтор того же события — тот же
    ключ; возврат на прежние статус или дату — новое изменение и новое уведомление (не от значения, а от изменения)."""
    stamp = getattr(fulfillment, "updated_at", None)
    return stamp.isoformat() if hasattr(stamp, "isoformat") else ""


def delivery_status_changed(fulfillment, status: str, bot_reaches: Optional[bool] = None) -> None:
    """Статус поставки (только колокольчик). Объект — поставка сделки: она одна на сделку (`Fulfillment.deal` — один к
    одному) и в кабинете открывается внутри проекта, поэтому `object.id` — id сделки, как в `start_param=delivery_<id>`.
    """
    code = fulfillment.status.code if getattr(fulfillment, "status_id", None) else ""
    if code in CLIENT_DECISION_STATUSES:
        return
    deal = fulfillment.deal
    notify(
        "delivery_status_changed",
        company=deal.company,
        object_id=deal.pk,
        object_number=_deal_ref(deal),
        params={"deal": _deal_ref(deal), "status": status},
        link=f"/deals/{deal.pk}",
        dedup=f"{fulfillment.pk}:{status}:{_change_stamp(fulfillment)}",
        bot_reaches=bot_reaches,
        document_contact_ids=_document_contacts(deal),
    )


def delivery_eta_changed(fulfillment, previous_eta, bot_reaches: Optional[bool] = None) -> None:
    """Сдвиг срока поставки — важное. Ключ — от изменения, а не от даты: возврат на прежнюю дату тоже сообщается."""
    deal = fulfillment.deal
    eta = fulfillment.expected_delivery_date.isoformat() if fulfillment.expected_delivery_date else ""
    previous = previous_eta.isoformat() if hasattr(previous_eta, "isoformat") else str(previous_eta or "")
    notify(
        "delivery_eta_changed",
        company=deal.company,
        object_id=deal.pk,
        object_number=_deal_ref(deal),
        params={"deal": _deal_ref(deal), "eta": eta, "previous_eta": previous},
        link=f"/deals/{deal.pk}",
        dedup=f"{fulfillment.pk}:{previous}>{eta}:{_change_stamp(fulfillment)}",
        bot_reaches=bot_reaches,
        document_contact_ids=_document_contacts(deal),
    )


def manager_replied(message) -> None:
    """Ответ менеджера в чате кабинета (CHAT-1, `crm.cabinet.message_sent`) — колокольчик всем контактам компании.

    Письмо — через 10 минут, если не прочитано (в колокольчике или в чате) и контакт не был в кабинете; тому, кто сейчас в
    чате, — только лента. Бот CRM ответы канала `cabinet` в Telegram не шлёт, поэтому письмо получает и контакт с Telegram
    (временное решение архитектора, DECISIONS 2026-11-04). Объект — чат, `id` — сообщение (прочтение ленты до него гасит
    уведомление).
    """
    from .notices import present_contacts

    company = message.company
    present = present_contacts(company.pk)
    notify(
        "manager_replied",
        company=company,
        object_id=message.pk,
        object_number="",
        params={"author": message.author_name or ""},
        link="/messages",
        dedup=f"{message.pk}",
        bot_reaches=False,
        email_skip={contact_id: "present" for contact_id in present},
    )


#: Решения по карточке партнёра (PART-3) → вид уведомления.
PARTNER_DECISIONS = {"published": "partner_card_published", "returned": "partner_card_returned"}


def partner_card_decision(product, decision: str, *, reason: str = "", issues=(), actor=None) -> int:
    """Решение по карточке партнёра (PART-3, очередь проверки) — колокольчик и письмо контактам партнёра.

    Подпись — как у `portal.services.partner_decision_mail.notify_decision` PART-3: очередь проверки зовёт эту функцию
    вместо прямого письма, второго письма нет. Партнёру без модуля «Мои товары» писать незачем — 0. Замечания по полям
    остаются в карточке (письмо ведёт в неё), в параметрах — только их число. Возвращает число строк ленты.
    """
    from .access import company_access

    company = getattr(product, "source_supplier", None)
    kind = PARTNER_DECISIONS.get(decision)
    if company is None or kind is None:
        return 0
    _roles, modules = company_access(company.pk)
    if "my_products" not in modules:
        return 0
    rows = notify(
        kind,
        company=company,
        object_id=product.pk,
        object_number=(product.name or "")[:100],
        params={"number": product.name or "", "reason": reason or "", "issues": str(len(list(issues or ())))},
        link=f"/my-products?card={product.pk}",
        dedup=f"{product.pk}:{timezone.now().isoformat()}",  # каждое решение — новое уведомление
        bot_reaches=False,
    )
    return len(rows)
