"""События EDS в ERP (волна 12, ADR-0015; `packages/contracts/events/eds/`): резолюция, отказ по письму, решение по КП.

* `uz.railtech.eds.letter.resolved.v1` (EDS-01) → задание расчёта по сделке и стадия «Расчёт» (`crm/services/calc_tasks.py`);
* `uz.railtech.eds.letter.rejected.v1` → сделка `CLOSED_LOST` с причиной;
* `uz.railtech.eds.approval.decided.v1` (EDS-03), объект — КП → решение директора на КП
  (`crm/services/eds_quote_approval.py`); решения по документам EDS ERP не касаются.

Сделка письма — `links.erp_deal_id`, иначе `links.erp_request_id` (у ERP заявка и есть сделка: `request.created` несёт
`erp_request_id = id сделки`). Нет ссылки или сделки — пропуск с записью в журнал (`ActivityLog`, уровень WARNING),
не ошибка: повтор такого события ничего бы не изменил. Повтор события — без дублей (идемпотентность — в сервисах).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from crm.models import Deal
from crm.services import calc_tasks, eds_quote_approval

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    applied: bool
    reason: str = ""


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _deal_of(data: dict[str, Any], event: str) -> Optional[Deal]:
    links = data.get("links") or {}
    letter = data.get("letter") or {}
    deal_id = links.get("erp_deal_id") or links.get("erp_request_id")
    deal = Deal.objects.filter(pk=deal_id).first() if deal_id else None
    if deal is None:
        why = "письмо не связано со сделкой ERP" if not deal_id else f"сделки #{deal_id} в ERP нет"
        logger.warning("%s %s: %s — пропуск", event, letter.get("number"), why)
        calc_tasks.deal_log(
            None,
            f"Событие EDS {event} пропущено",
            f"{letter.get('number', '—')}: {why}",
            event_code="eds.letter_skipped",
            event_params={"event": event, "letter_number": letter.get("number"), "erp_deal_id": deal_id},
            level="WARNING",
        )
    return deal


def apply_letter_resolved(data: dict[str, Any], event_id: Optional[UUID] = None) -> Outcome:
    """`letter.resolved` → задание расчёта (исполнители, срок, порог маржи) и сделка в «Расчёт»."""
    deal = _deal_of(data, "letter.resolved")
    if deal is None:
        return Outcome(False, "no_deal")
    letter, resolution = data["letter"], data["resolution"]
    margin = resolution.get("min_margin_pct")
    outcome = calc_tasks.apply_resolution(
        deal,
        eds_letter_id=UUID(letter["eds_letter_id"]),
        letter_number=letter["number"],
        letter_subject=letter.get("subject") or "",
        text=resolution["text"],
        due=date.fromisoformat(resolution["due"]),
        min_margin_pct=Decimal(margin) if margin is not None else None,
        decided_by_crm_user_id=resolution["decided_by"].get("crm_user_id"),
        decided_by_name=resolution["decided_by"].get("full_name") or "",
        decided_at=_when(resolution["decided_at"]),
        assignees=[calc_tasks.Assignment(int(a["crm_user_id"]), a["zone"]) for a in resolution["assignees"]],
        event_id=event_id,
    )
    return Outcome(outcome.changed, "" if outcome.changed else "duplicate")


def apply_letter_rejected(data: dict[str, Any]) -> Outcome:
    """`letter.rejected` → сделка `CLOSED_LOST` с причиной отказа."""
    deal = _deal_of(data, "letter.rejected")
    if deal is None:
        return Outcome(False, "no_deal")
    applied = calc_tasks.apply_letter_rejection(deal, letter_number=data["letter"]["number"], reason=data["reason"])
    return Outcome(applied, "" if applied else "unchanged")


def apply_approval_decided(data: dict[str, Any]) -> Outcome:
    """`approval.decided` по КП → решение директора на КП; прочие объекты маршрутов (документы EDS) — не ERP."""
    approval_object = data["approval"]["object"]
    if approval_object.get("kind") != "quote":
        return Outcome(False, "not_a_quote")
    result = eds_quote_approval.apply_director_decision(
        erp_quote_id=int(approval_object["erp_quote_id"]),
        quote_version=int(approval_object["quote_version"]),
        decision=data["decision"],
        route_status=data["route_status"],
        comment=data.get("comment"),
        outgoing_number=data.get("outgoing_number"),
        channels=data.get("channels"),
        decided_by=data.get("decided_by") or {},
        decided_at=_when(data["decided_at"]),
        approved_late=bool(data.get("approved_late")),
    )
    return Outcome(result == "applied", result)


def apply_document_signed(data: dict[str, Any], event_id: Optional[UUID] = None) -> Outcome:
    """`document.signed` → проекция официального документа в PortalDocumentVerification для публичной проверки (ADR-0024 §6, SIGN-VERIFY-1)."""
    doc = data.get("document") or {}
    code = doc.get("verification_code")
    if not code:
        logger.warning("eds.document.signed: нет verification_code — пропуск")
        return Outcome(False, "no_verification_code")

    from portal.models import PortalDocumentVerification

    from core.tenant import own_company

    company = own_company()
    company_name = company.name if company else "RailTech"

    signer = doc.get("signer") or {}
    signed_at_str = doc.get("signed_at")
    signed_at_dt = _when(signed_at_str) if signed_at_str else None
    doc_date = signed_at_dt.date() if signed_at_dt else date.today()

    basis_val = doc.get("basis") or "charter"
    basis_text = doc.get("basis_text") or ("на основании Устава" if basis_val == "charter" else "")

    eds_doc_id_raw = doc.get("eds_document_id")
    eds_doc_id = UUID(str(eds_doc_id_raw)) if eds_doc_id_raw else None

    obj, created = PortalDocumentVerification.objects.update_or_create(
        code=code,
        defaults={
            "kind": doc.get("kind") or "letter_out",
            "number": doc.get("number") or "",
            "date": doc_date,
            "company_name": company_name,
            "signatory_name": signer.get("name") or "",
            "signatory_position": signer.get("position") or "",
            "signatory_basis": basis_text,
            "status": "valid",
            "sha256_hash": doc.get("pdf_hash"),
            "signed_at": signed_at_dt,
            "eds_document_id": eds_doc_id,
        },
    )
    logger.info("eds.document.signed: сохранена проекция проверки документа %s (#%s)", code, obj.number)
    return Outcome(True, "created" if created else "updated")


def apply_signing_decided(data: dict[str, Any], event_id: Optional[UUID] = None) -> Outcome:
    """`signing.decided` (SIGN-4, ADR-0024): решение уполномоченного лица EDS по коммерческому документу ERP.

    Объект — `object.kind` ("quote", "contract", "invoice", "act"), `object.object_id`, `object.number`.
    `decision`: "signed" | "rejected".
    """
    obj = data.get("object") or {}
    kind = obj.get("kind")
    object_id = obj.get("object_id")
    decision = data.get("decision")

    if not kind or not object_id:
        logger.warning("eds.signing.decided: нет kind или object_id — пропуск")
        return Outcome(False, "invalid_object")

    from portal.models import PortalDocumentVerification

    from core.tenant import own_company

    company = own_company()
    company_name = company.name if company else "RailTech"

    if decision == "signed":
        code = data.get("verification_code")
        signer = data.get("signer") or {}
        signed_at_str = data.get("signed_at")
        signed_at_dt = _when(signed_at_str) if signed_at_str else datetime.now()
        basis_val = data.get("basis") or "charter"
        basis_text = data.get("basis_text") or ("на основании Устава" if basis_val == "charter" else "")
        signer_name = signer.get("full_name") or signer.get("name") or ""
        signer_position = signer.get("position") or ""

        # 1. Обновляем публичную проекцию PortalDocumentVerification
        if code:
            PortalDocumentVerification.objects.update_or_create(
                code=code,
                defaults={
                    "kind": kind,
                    "number": obj.get("number") or "",
                    "date": signed_at_dt.date(),
                    "company_name": company_name,
                    "signatory_name": signer_name,
                    "signatory_position": signer_position,
                    "signatory_basis": basis_text,
                    "status": "valid",
                    "sha256_hash": None,
                    "signed_at": signed_at_dt,
                    "eds_document_id": None,
                },
            )

        # 2. Обновляем целевой документ в ERP
        if kind == "quote":
            from sales.models import Quote

            from crm.services.quotes.lifecycle import QuoteLifecycleService

            quote = Quote.objects.filter(pk=object_id).first()
            if not quote:
                logger.warning("eds.signing.decided: Quote #%s не найден", object_id)
                return Outcome(False, "quote_not_found")

            quote.verification_code = code or ""
            quote.signatory_name = signer_name
            quote.signatory_position = signer_position
            quote.signatory_basis = basis_val
            quote.signatory_basis_text = basis_text
            quote.signed_at = signed_at_dt
            quote.save(
                update_fields=[
                    "verification_code",
                    "signatory_name",
                    "signatory_position",
                    "signatory_basis",
                    "signatory_basis_text",
                    "signed_at",
                ]
            )
            QuoteLifecycleService.generate_pdf(quote.pk)
            logger.info("eds.signing.decided: Quote #%s подписано уполномоченным (%s)", object_id, code)
            return Outcome(True, "quote_signed")

        elif kind == "contract":
            from sales.models import Contract

            from crm.services.contracts import _render_contract_pdf

            contract = Contract.objects.filter(pk=object_id).first()
            if not contract:
                logger.warning("eds.signing.decided: Contract #%s не найден", object_id)
                return Outcome(False, "contract_not_found")

            contract.verification_code = code or ""
            contract.signatory_name = signer_name
            contract.signatory_position = signer_position
            contract.signatory_basis = basis_val
            contract.signatory_basis_text = basis_text
            contract.signed_at = signed_at_dt
            contract.manager_signed_at = signed_at_dt
            contract.save(
                update_fields=[
                    "verification_code",
                    "signatory_name",
                    "signatory_position",
                    "signatory_basis",
                    "signatory_basis_text",
                    "signed_at",
                    "manager_signed_at",
                ]
            )
            _render_contract_pdf(contract)
            logger.info("eds.signing.decided: Contract #%s подписан уполномоченным (%s)", object_id, code)
            return Outcome(True, "contract_signed")

        elif kind == "invoice":
            from finance.models import Invoice

            from crm.services.billing import _render_invoice_pdf

            invoice = Invoice.objects.filter(pk=object_id).first()
            if not invoice:
                logger.warning("eds.signing.decided: Invoice #%s не найден", object_id)
                return Outcome(False, "invoice_not_found")

            invoice.verification_code = code or ""
            invoice.signatory_name = signer_name
            invoice.signatory_position = signer_position
            invoice.signatory_basis = basis_val
            invoice.signatory_basis_text = basis_text
            invoice.signed_at = signed_at_dt
            invoice.save(
                update_fields=[
                    "verification_code",
                    "signatory_name",
                    "signatory_position",
                    "signatory_basis",
                    "signatory_basis_text",
                    "signed_at",
                ]
            )
            _render_invoice_pdf(invoice)
            logger.info("eds.signing.decided: Invoice #%s подписан уполномоченным (%s)", object_id, code)
            return Outcome(True, "invoice_signed")

        elif kind == "act":
            from finance.models import Act

            from crm.services.billing import _render_act_pdf

            act = Act.objects.filter(pk=object_id).first()
            if not act:
                logger.warning("eds.signing.decided: Act #%s не найден", object_id)
                return Outcome(False, "act_not_found")

            act.verification_code = code or ""
            act.signatory_name = signer_name
            act.signatory_position = signer_position
            act.signatory_basis = basis_val
            act.signatory_basis_text = basis_text
            act.signed_at = signed_at_dt
            act.issuer_signed_at = signed_at_dt
            act.save(
                update_fields=[
                    "verification_code",
                    "signatory_name",
                    "signatory_position",
                    "signatory_basis",
                    "signatory_basis_text",
                    "signed_at",
                    "issuer_signed_at",
                ]
            )
            _render_act_pdf(act)
            logger.info("eds.signing.decided: Act #%s подписан уполномоченным (%s)", object_id, code)
            return Outcome(True, "act_signed")

    elif decision == "rejected":
        comment = data.get("comment") or "Отказ в подписании документа"
        logger.warning("eds.signing.decided: документ %s #%s отклонен: %s", kind, object_id, comment)
        return Outcome(True, "rejected")

    return Outcome(False, f"unknown_decision: {decision}")
