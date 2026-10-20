"""Django signals to automatically emit integration webhooks on ERP mutations (CONTRACTS §3, M3-ERP-02).

События:
- request.created (создание сделки/заявки)
- deal.stage_changed, deal.won, deal.lost (мутации сделки)
- quote.sent, quote.accepted, quote.rejected (мутации статуса КП)
- contract.signed (подписание договора)
- invoice.issued, invoice.paid, invoice.overdue (статусы счетов)
- act.issued, act.accepted, act.returned (статусы актов)
- delivery.status_changed, delivery.eta_changed (статусы и сроки исполнения)
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_save, pre_save

from .services import webhooks

logger = logging.getLogger(__name__)

#: Допустимые источники запроса в `request.created` (`events.schema.json`, `RequestCreated.source`).
REQUEST_SOURCES = ("crm", "cabinet", "erp")


# ─── Deal Signals ─────────────────────────────────────────────────────────────


def handle_deal_pre_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Запоминает предыдущую стадию сделки до сохранения."""
    if instance.pk:
        from sales.models import Deal

        prev = Deal.objects.filter(pk=instance.pk).select_related("stage").first()
        if prev and prev.stage:
            instance._prev_stage_code = prev.stage.code
        else:
            instance._prev_stage_code = None
    else:
        instance._prev_stage_code = None


def handle_deal_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует request.created при создании сделки и deal.stage_changed/won/lost при смене стадии."""
    try:
        if not instance.company_id:
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

        # Смена стадии
        prev_code = getattr(instance, "_prev_stage_code", None)
        curr_code = instance.stage.code if getattr(instance, "stage", None) else None

        if curr_code and prev_code != curr_code:
            prev_stage = webhooks.map_deal_stage(prev_code)
            curr_stage = webhooks.map_deal_stage(curr_code)

            if prev_stage != curr_stage:
                webhooks.emit_deal_stage_changed(
                    deal=instance,
                    from_stage=prev_stage,
                    to_stage=curr_stage,
                )

            if curr_stage == "won":
                webhooks.emit_deal_outcome(deal=instance, won=True)
            elif curr_stage == "lost":
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
        if not getattr(instance, "deal_id", None):
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
    if instance.pk:
        from sales.models import Contract

        prev = Contract.objects.filter(pk=instance.pk).first()
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
        if not getattr(instance, "deal_id", None):
            return

        client_signed = bool(instance.client_signed_at)
        manager_signed = bool(instance.manager_signed_at)
        prev_client = getattr(instance, "_prev_client_signed", False)
        prev_manager = getattr(instance, "_prev_manager_signed", False)

        curr_status = instance.status.code if getattr(instance, "status", None) else ""
        prev_status = getattr(instance, "_prev_status_code", "")

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
        if not getattr(instance, "deal_id", None):
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
        if not getattr(instance, "deal_id", None):
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
        if not getattr(instance, "deal_id", None):
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

    try:
        from documents.models import GeneratedDocument

        post_save.connect(handle_document_post_save, sender=GeneratedDocument, dispatch_uid="int_doc_post_save")
    except Exception as exc:
        logger.warning("Could not register GeneratedDocument signal: %s", exc)


def handle_document_post_save(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Генерирует document.created при создании документа."""
    try:
        if created:
            webhooks.emit_document_created(document=instance)
    except Exception as exc:
        logger.error("Error in handle_document_post_save for Document #%s: %s", getattr(instance, "id", None), exc)
