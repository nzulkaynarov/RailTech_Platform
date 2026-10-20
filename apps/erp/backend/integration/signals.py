"""Django signals to automatically emit integration webhooks on ERP mutations (CONTRACTS §3, M3-ERP-02).

События:
- request.created (создание сделки/заявки)
- deal.stage_changed, deal.won, deal.lost (мутации сделки)
- quote.sent, quote.accepted, quote.rejected (мутации статуса КП)
- contract.signed (подписание договора)
- invoice.issued, invoice.paid, invoice.overdue (статусы счетов)
- act.issued, act.accepted, act.returned (статусы актов)
- delivery.status_changed, delivery.eta_changed (статусы и сроки исполнения)
- document.created (документ выпущен клиенту: КП, договор, счёт, акт, накладная, `GeneratedDocument`; FIX-38)
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_save, pre_save
from portal.services import documents as portal_documents

from .services import stages, webhooks

logger = logging.getLogger(__name__)


#: Поля, от которых зависят события сигналов: save без них в `update_fields` прежнюю запись не читает.
DEAL_TRACKED = ("stage",)
QUOTE_TRACKED = ("status",)
CONTRACT_TRACKED = ("status", "client_signed_at", "manager_signed_at")
INVOICE_TRACKED = ("status",)
ACT_TRACKED = ("status",)
FULFILLMENT_TRACKED = ("status", "expected_delivery_date")
#: `document.created` зависит от того, выпущена ли запись (`portal.services.documents.is_issued`): статус и поля предикатов.
DOCUMENT_TRACKED = {
    "quote": ("status", "public_access_token"),
    "contract": ("status",),
    "invoice": ("status", "due_date", "issued_at"),
    "act": ("status", "rejection_reason"),
    "waybill": ("status",),
    "generated": ("status", "template"),
}


def _untracked_save(
    instance: Any, update_fields: Any, tracked: tuple[str, ...], flag: str = "_int_untracked_save"
) -> bool:
    """`save(update_fields=[...])` без отслеживаемых полей: прежнюю запись читать незачем, событий не будет.

    Помечает экземпляр (`flag`, по умолчанию `_int_untracked_save`) — post_save-обработчик такой save пропускает, не сравнивая состояния.
    Без `update_fields` (полный save) и для новой записи читаем как раньше. FK можно назвать и `stage`, и `stage_id`.
    """
    names = set(update_fields) if update_fields is not None else None
    untracked = bool(
        instance.pk
        and names is not None
        and not names & (set(tracked) | {f"{name}_id" for name in tracked})
    )
    setattr(instance, flag, untracked)
    return untracked


#: Допустимые источники запроса в `request.created` (`events.schema.json`, `RequestCreated.source`).
REQUEST_SOURCES = ("crm", "cabinet", "erp")


# ─── Deal Signals ─────────────────────────────────────────────────────────────


def handle_deal_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает предыдущую стадию сделки до сохранения.

    Единственное чтение прежней записи на оба потребителя: вебхуки (`_prev_stage_code`) и уведомление клиенту
    (`_prev_stage_id`, `notifications.signals.notify_deal_stage_change` — post_save).
    """
    if _untracked_save(instance, kwargs.get("update_fields"), DEAL_TRACKED):
        instance._prev_stage_id = instance.stage_id
        return
    if instance.pk:
        from sales.models import Deal

        prev = Deal.objects.filter(pk=instance.pk).select_related("stage").first()
        instance._prev_stage_code = stages.fsm_code(prev) if prev else None
        instance._prev_stage_id = prev.stage_id if prev else None
    else:
        instance._prev_stage_code = None
        instance._prev_stage_id = None


def handle_deal_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует request.created при создании сделки и deal.stage_changed/won/lost при смене стадии."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not instance.company_id:
            return

        if created:
            # Откуда запрос, решает тот, кто его создал: портал ставит `request_origin` (FIX-23), и только он даёт
            # `cabinet`. Контакт у сделки ничего не доказывает — его ставит и сотрудник; без признака — `erp`.
            origin = getattr(instance, "request_origin", None) or {}
            source = origin.get("source") if origin.get("source") in REQUEST_SOURCES else "erp"
            webhooks.emit_request_created(
                deal=instance,
                source=source,
                erp_request_id=getattr(instance, "portal_request_id", None) or instance.id,
                summary=origin.get("summary") or instance.title or f"Заявка #{instance.id}",
                actor=origin.get("actor"),  # erp-mcp (FIX-36): агент CRM — actor `client`, клиент CRM из контекста
                crm_client_id=origin.get("crm_client_id"),
            )
            return

        # Смена стадии FSM. Стадия контракта — из `stages.deal_stage` (с прежним кодом FSM и нынешними документами);
        # итог продажи (`deal.won` / `deal.lost`) определяет сам переход FSM в CLOSED_WON / CLOSED_LOST.
        prev_code = getattr(instance, "_prev_stage_code", None)
        curr_code = stages.fsm_code(instance)

        if curr_code and prev_code != curr_code:
            prev_stage = stages.deal_stage(instance, with_fsm_code=prev_code)
            curr_stage = stages.deal_stage(instance)

            if prev_stage != curr_stage:
                webhooks.emit_deal_stage_changed(
                    deal=instance,
                    from_stage=prev_stage,
                    to_stage=curr_stage,
                )

            outcome = stages.fsm_outcome(curr_code)
            if outcome == "won":
                webhooks.emit_deal_outcome(deal=instance, won=True)
            elif outcome == "lost":
                webhooks.emit_deal_outcome(
                    deal=instance,
                    won=False,
                    lost_reason=getattr(instance, "lost_reason", "") or "Сделка закрыта со статусом lost",
                )
    except Exception as exc:
        logger.error("Error in handle_deal_post_save for Deal #%s: %s", getattr(instance, "id", None), exc)


# ─── Quote Signals ────────────────────────────────────────────────────────────


def handle_quote_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает предыдущий статус КП до сохранения."""
    if _untracked_save(instance, kwargs.get("update_fields"), QUOTE_TRACKED):
        return
    if instance.pk:
        from sales.models import Quote

        prev = Quote.objects.filter(pk=instance.pk).select_related("status").first()
        if prev and prev.status:
            instance._prev_status_code = prev.status.code
        else:
            instance._prev_status_code = None
    else:
        instance._prev_status_code = None


def handle_quote_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует quote.sent, quote.accepted, quote.rejected при смене статуса КП."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not getattr(instance, "deal_id", None):
            return

        prev_status = getattr(instance, "_prev_status_code", None)
        curr_status = instance.status.code if getattr(instance, "status", None) else None

        if not curr_status:
            return

        status_norm = curr_status.upper()
        prev_norm = (prev_status or "").upper()

        if status_norm != prev_norm:
            if status_norm == "SENT":
                webhooks.emit_quote_sent(quote=instance)
            elif status_norm in ("APPROVED", "ACCEPTED"):
                webhooks.emit_quote_outcome(event_type="quote.accepted", quote=instance)
            elif status_norm == "REJECTED":
                webhooks.emit_quote_outcome(event_type="quote.rejected", quote=instance)

    except Exception as exc:
        logger.error("Error in handle_quote_post_save for Quote #%s: %s", getattr(instance, "id", None), exc)


# ─── Contract Signals ─────────────────────────────────────────────────────────


def handle_contract_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает состояние подписи договора до сохранения."""
    if _untracked_save(instance, kwargs.get("update_fields"), CONTRACT_TRACKED):
        return
    if instance.pk:
        from sales.models import Contract

        prev = Contract.objects.filter(pk=instance.pk).select_related("status").first()
        if prev:
            instance._prev_client_signed = bool(prev.client_signed_at)
            instance._prev_manager_signed = bool(prev.manager_signed_at)
            instance._prev_status_code = prev.status.code if prev.status else None
        else:
            instance._prev_client_signed = False
            instance._prev_manager_signed = False
            instance._prev_status_code = None
    else:
        instance._prev_client_signed = False
        instance._prev_manager_signed = False
        instance._prev_status_code = None


def handle_contract_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует contract.signed при подписании."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not getattr(instance, "deal_id", None):
            return

        client_signed = bool(instance.client_signed_at)
        manager_signed = bool(instance.manager_signed_at)
        prev_client = getattr(instance, "_prev_client_signed", False)
        prev_manager = getattr(instance, "_prev_manager_signed", False)

        # У нового договора прежнего статуса нет (`None`): без `or ""` `.upper()` падал, а исключение глоталось ниже,
        # и `contract.signed` по договору, созданному уже подписанным, не уходил.
        curr_status = (instance.status.code if getattr(instance, "status", None) else "") or ""
        prev_status = getattr(instance, "_prev_status_code", None) or ""

        is_new_signature = (client_signed and not prev_client) or (manager_signed and not prev_manager)
        status_became_signed = (
            curr_status.upper() in ("SIGNED", "SIGNED_BY_CLIENT") and prev_status.upper() != curr_status.upper()
        )

        if is_new_signature or status_became_signed:
            if client_signed and manager_signed:
                by = "both"
            elif client_signed:
                by = "client"
            else:
                by = "company"

            webhooks.emit_contract_signed(contract=instance, by=by)
    except Exception as exc:
        logger.error("Error in handle_contract_post_save for Contract #%s: %s", getattr(instance, "id", None), exc)


# ─── Invoice Signals ──────────────────────────────────────────────────────────


def handle_invoice_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает статус инвойса до сохранения."""
    if _untracked_save(instance, kwargs.get("update_fields"), INVOICE_TRACKED):
        return
    if instance.pk:
        from finance.models import Invoice

        prev = Invoice.objects.filter(pk=instance.pk).select_related("status").first()
        if prev and prev.status:
            instance._prev_status_code = prev.status.code
        else:
            instance._prev_status_code = None
    else:
        instance._prev_status_code = None


def handle_invoice_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует invoice.issued, invoice.paid, invoice.overdue."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not getattr(instance, "deal_id", None):
            return

        curr_status = instance.status.code if getattr(instance, "status", None) else None
        if not curr_status:
            return

        prev_status = getattr(instance, "_prev_status_code", None)
        curr_norm = curr_status.upper()
        prev_norm = (prev_status or "").upper()

        if (created and curr_norm == "ISSUED") or (prev_norm != curr_norm and curr_norm == "ISSUED"):
            webhooks.emit_invoice_event("invoice.issued", invoice=instance)
        elif prev_norm != curr_norm and curr_norm == "PAID":
            webhooks.emit_invoice_event("invoice.paid", invoice=instance)
        elif prev_norm != curr_norm and curr_norm == "OVERDUE":
            webhooks.emit_invoice_event("invoice.overdue", invoice=instance)
    except Exception as exc:
        logger.error("Error in handle_invoice_post_save for Invoice #%s: %s", getattr(instance, "id", None), exc)


# ─── Act Signals ──────────────────────────────────────────────────────────────


def handle_act_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает статус акта до сохранения."""
    if _untracked_save(instance, kwargs.get("update_fields"), ACT_TRACKED):
        return
    if instance.pk:
        from finance.models import Act

        prev = Act.objects.filter(pk=instance.pk).select_related("status").first()
        if prev and prev.status:
            instance._prev_status_code = prev.status.code
        else:
            instance._prev_status_code = None
    else:
        instance._prev_status_code = None


def handle_act_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует act.issued, act.accepted, act.returned."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not getattr(instance, "deal_id", None):
            return

        curr_status = instance.status.code if getattr(instance, "status", None) else None
        if not curr_status:
            return

        prev_status = getattr(instance, "_prev_status_code", None)
        curr_norm = curr_status.upper()
        prev_norm = (prev_status or "").upper()

        if (created and curr_norm == "ISSUED") or (prev_norm != curr_norm and curr_norm == "ISSUED"):
            webhooks.emit_act_event("act.issued", act=instance)
        elif prev_norm != curr_norm and curr_norm in ("ACCEPTED", "SIGNED"):
            webhooks.emit_act_event("act.accepted", act=instance)
        elif prev_norm != curr_norm and curr_norm in ("RETURNED", "DISPUTED", "REJECTED"):
            webhooks.emit_act_event("act.returned", act=instance)
    except Exception as exc:
        logger.error("Error in handle_act_post_save for Act #%s: %s", getattr(instance, "id", None), exc)


# ─── Fulfillment Signals ──────────────────────────────────────────────────────


def handle_fulfillment_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает статус и ETA до сохранения."""
    if _untracked_save(instance, kwargs.get("update_fields"), FULFILLMENT_TRACKED):
        return
    if instance.pk:
        from sales.models import Fulfillment

        prev = Fulfillment.objects.filter(pk=instance.pk).select_related("status").first()
        if prev:
            instance._prev_status_code = prev.status.code if prev.status else None
            instance._prev_eta = prev.expected_delivery_date
        else:
            instance._prev_status_code = None
            instance._prev_eta = None
    else:
        instance._prev_status_code = None
        instance._prev_eta = None


def handle_fulfillment_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует delivery.status_changed и delivery.eta_changed."""
    try:
        if getattr(instance, "_int_untracked_save", False) or not getattr(instance, "deal_id", None):
            return

        prev_status = getattr(instance, "_prev_status_code", None)
        curr_status = instance.status.code if getattr(instance, "status", None) else None

        prev_eta = getattr(instance, "_prev_eta", None)
        curr_eta = instance.expected_delivery_date

        if curr_status and (prev_status != curr_status or created):
            webhooks.emit_delivery_event(
                event_type="delivery.status_changed",
                fulfillment=instance,
                previous_eta=prev_eta,
            )

        if prev_eta and curr_eta and prev_eta != curr_eta:
            webhooks.emit_delivery_event(
                event_type="delivery.eta_changed",
                fulfillment=instance,
                previous_eta=prev_eta,
            )
    except Exception as exc:
        logger.error(
            "Error in handle_fulfillment_post_save for Fulfillment #%s: %s", getattr(instance, "id", None), exc
        )


def register_signals() -> None:
    """Регистрирует сигналы для моделей ERP."""
    from finance.models import Act, Invoice
    from sales.models import Contract, Deal, Fulfillment, Quote

    pre_save.connect(handle_deal_pre_save, sender=Deal, dispatch_uid="int_deal_pre_save")
    post_save.connect(handle_deal_post_save, sender=Deal, dispatch_uid="int_deal_post_save")

    pre_save.connect(handle_quote_pre_save, sender=Quote, dispatch_uid="int_quote_pre_save")
    post_save.connect(handle_quote_post_save, sender=Quote, dispatch_uid="int_quote_post_save")

    pre_save.connect(handle_contract_pre_save, sender=Contract, dispatch_uid="int_contract_pre_save")
    post_save.connect(handle_contract_post_save, sender=Contract, dispatch_uid="int_contract_post_save")

    pre_save.connect(handle_invoice_pre_save, sender=Invoice, dispatch_uid="int_invoice_pre_save")
    post_save.connect(handle_invoice_post_save, sender=Invoice, dispatch_uid="int_invoice_post_save")

    pre_save.connect(handle_act_pre_save, sender=Act, dispatch_uid="int_act_pre_save")
    post_save.connect(handle_act_post_save, sender=Act, dispatch_uid="int_act_post_save")

    pre_save.connect(handle_fulfillment_pre_save, sender=Fulfillment, dispatch_uid="int_fulfillment_pre_save")
    post_save.connect(handle_fulfillment_post_save, sender=Fulfillment, dispatch_uid="int_fulfillment_post_save")

    register_document_signals()


# ─── Document Signals (FIX-38) ────────────────────────────────────────────────


def register_document_signals() -> None:
    """`document.created` — когда документ становится виден клиенту, у каждого источника документов портала."""
    from documents.models import GeneratedDocument
    from finance.models import Act, Invoice
    from sales.models import Contract, Fulfillment, Quote

    sources = {
        GeneratedDocument: "generated",
        Quote: "quote",
        Contract: "contract",
        Invoice: "invoice",
        Act: "act",
        Fulfillment: "waybill",
    }
    for model, source in sources.items():
        _DOCUMENT_SOURCES[model] = source
        pre_save.connect(handle_document_pre_save, sender=model, dispatch_uid=f"int_doc_pre_save_{source}")
        post_save.connect(handle_document_post_save, sender=model, dispatch_uid=f"int_doc_post_save_{source}")


#: Модель → источник документа портала (`portal.services.documents.SLOT_BY_SOURCE`); заполняет `register_document_signals`.
_DOCUMENT_SOURCES: dict[type, str] = {}


def handle_document_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает, был ли документ выпущен до сохранения: событие шлётся на переходе, а не на каждом сохранении."""
    try:
        source = _DOCUMENT_SOURCES[sender]
        if _untracked_save(instance, kwargs.get("update_fields"), DOCUMENT_TRACKED[source], flag="_doc_untracked_save"):
            # Выпуск не мог поменяться: перехода нет, и читать прежнюю запись незачем.
            instance._document_was_issued = True
            return
        related = ("status", "template__kind") if source == "generated" else ("status",)
        previous = sender.objects.select_related(*related).filter(pk=instance.pk).first() if instance.pk else None
        instance._document_was_issued = previous is not None and portal_documents.is_issued(source, previous)
    except Exception as exc:
        instance._document_was_issued = False
        logger.error("Error in handle_document_pre_save for %s #%s: %s", sender.__name__, instance.pk, exc)


def handle_document_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует document.created, когда документ стал выпущенным (в том числе при создании сразу выпущенным).

    Правило выпуска — единое с порталом (`portal.services.documents.is_issued`): черновики, КП до отправки, отменённые
    документы, письма и рапорты событий не дают. Скан подписанного акта (входящий файл клиента) — не документ ERP.
    """
    try:
        source = _DOCUMENT_SOURCES[sender]
        if getattr(instance, "_document_was_issued", False) or not portal_documents.is_issued(source, instance):
            return
        if source == "generated" and portal_documents.is_portal_scan(instance):
            return
        company = _document_company(source, instance)
        document = (
            portal_documents.find_client_document(company, portal_documents.encode_document_id(source, instance.pk))
            if company is not None
            else None
        )
        if document is not None:
            webhooks.emit_document_created(document=document)
    except Exception as exc:
        logger.error("Error in handle_document_post_save for %s #%s: %s", sender.__name__, instance.pk, exc)


def _document_company(source: str, instance: Any):
    """Компания клиента, которой принадлежит документ: по сделке, у `GeneratedDocument` без сделки — по контакту."""
    if instance.deal_id and instance.deal.company_id:
        return instance.deal.company
    if source == "generated" and instance.contact_id and instance.contact.company_id:
        return instance.contact.company
    return None
