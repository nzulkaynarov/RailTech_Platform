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

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

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


def _signing_doc(kind: str, object_id: int):
    """Документ ERP запроса подписи или `None`."""
    from finance.models import Act, Invoice
    from sales.models import Contract, Quote

    model = {"quote": Quote, "contract": Contract, "invoice": Invoice, "act": Act}.get(kind)
    return model.objects.select_for_update().filter(pk=object_id).first() if model else None


def _render_signed_pdf(kind: str, doc: Any) -> None:
    from crm.services.billing import _render_act_pdf, _render_invoice_pdf
    from crm.services.contracts import _render_contract_pdf
    from crm.services.quotes.lifecycle import QuoteLifecycleService

    if kind == "quote":
        QuoteLifecycleService.generate_pdf(doc.pk)
    elif kind == "contract":
        _render_contract_pdf(doc)
    elif kind == "invoice":
        _render_invoice_pdf(doc)
    else:
        _render_act_pdf(doc)


def _pdf_sha256(doc: Any) -> Optional[str]:
    """SHA-256 итогового PDF для проверки подлинности (ADR-0024 п. 6); нет файла — `None`."""
    pdf = getattr(doc, "pdf_file", None)
    if not pdf:
        return None
    try:
        with pdf.open("rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except (OSError, ValueError):
        logger.exception("eds.signing.decided: не удалось прочитать PDF для хеша")
        return None


def _notify_author(request: Any, title: str, message: str) -> None:
    """Автор запроса узнаёт итог; сбой уведомления решение не отменяет."""
    from notifications.services import notify_user

    if request.requested_by is None:
        return
    try:
        notify_user(user=request.requested_by, title=title, message=message, type_code="INFO", event_code="signing.decided")
    except Exception:
        logger.exception("eds.signing.decided: не удалось уведомить автора")


_STAMP_FIELDS = ["verification_code", "signatory_name", "signatory_position", "signatory_basis", "signatory_basis_text"]
_KIND_LABELS = {"quote": "КП", "contract": "договор", "invoice": "счёт", "act": "акт"}


def apply_signing_decided(data: dict[str, Any], event_id: Optional[UUID] = None) -> Outcome:
    """`signing.decided` (SIGN-4, FX-10): итог подписи коммерческого документа в EDS.

    Решение применяется только к открытому запросу и только к той редакции документа, что ушла на подпись. Проекция для
    публичной проверки появляется после штампа и PDF: без документа её нет.
    """
    from crm.services.signing_outbound import fingerprint
    from integration.models import CommercialSigningRequest as Request
    from portal.models import PortalDocumentVerification

    from core.tenant import own_company

    obj = data.get("object") or {}
    kind = obj.get("kind")
    object_id = obj.get("object_id")
    decision = data.get("decision")
    if not kind or not object_id:
        logger.warning("eds.signing.decided: нет kind или object_id — пропуск")
        return Outcome(False, "invalid_object")
    if decision not in ("signed", "rejected"):
        return Outcome(False, f"unknown_decision: {decision}")

    with transaction.atomic():
        request = (
            Request.objects.select_for_update(of=("self",))
            .select_related("requested_by")
            .filter(kind=kind, object_id=object_id, status=Request.Status.PENDING)
            .first()
        )
        if request is None:
            logger.warning("eds.signing.decided: нет открытого запроса %s #%s", kind, object_id)
            return Outcome(False, "no_pending_request")
        label = f"{_KIND_LABELS.get(kind, kind)} {request.number}"
        now = timezone.now()

        if decision == "rejected":
            request.status, request.decided_at = Request.Status.REJECTED, now
            request.comment = data.get("comment") or "Отказ в подписании документа"
            request.save(update_fields=["status", "comment", "decided_at"])
            _notify_author(request, f"Отказ в подписи: {label}", request.comment)
            return Outcome(True, "rejected")

        doc = _signing_doc(kind, object_id)
        if doc is None:
            request.status, request.decided_at = Request.Status.REJECTED, now
            request.comment = "Документ не найден."
            request.save(update_fields=["status", "comment", "decided_at"])
            return Outcome(False, f"{kind}_not_found")
        if fingerprint(kind, doc) != request.fingerprint:
            request.status, request.decided_at = Request.Status.STALE, now
            request.comment = "Документ изменён после отправки на подпись. Отправьте его заново."
            request.save(update_fields=["status", "comment", "decided_at"])
            _notify_author(request, f"Подпись не применена: {label}", request.comment)
            return Outcome(True, "stale")

        signer = data.get("signer") or {}
        code = data.get("verification_code") or ""
        signed_at = _when(data["signed_at"]) if data.get("signed_at") else now
        basis = data.get("basis") or "charter"
        basis_text = data.get("basis_text") or ("на основании Устава" if basis == "charter" else "")
        signer_name = signer.get("full_name") or signer.get("name") or ""
        signer_position = signer.get("position") or ""

        doc.verification_code = code
        doc.signatory_name = signer_name
        doc.signatory_position = signer_position
        doc.signatory_basis = basis
        doc.signatory_basis_text = basis_text
        fields = list(_STAMP_FIELDS)
        if kind == "act":  # `act.signed_at` — приёмка клиентом; подпись компании — `issuer_signed_at`
            doc.issuer_signed_at = signed_at
            fields.append("issuer_signed_at")
        else:
            doc.signed_at = signed_at
            fields.append("signed_at")
        if kind == "contract":
            doc.manager_signed_at = signed_at
            fields.append("manager_signed_at")
        doc.save(update_fields=fields)
        _render_signed_pdf(kind, doc)
        doc.refresh_from_db()

        company = own_company()
        PortalDocumentVerification.objects.update_or_create(
            code=code,
            defaults={
                "kind": kind,
                "number": obj.get("number") or "",
                "date": signed_at.date(),
                "company_name": company.name if company else "RailTech",
                "signatory_name": signer_name,
                "signatory_position": signer_position,
                "signatory_basis": basis_text,
                "status": "valid",
                "sha256_hash": _pdf_sha256(doc),
                "signed_at": signed_at,
                "eds_document_id": None,
            },
        )
        request.status, request.decided_at, request.signer_name = Request.Status.SIGNED, now, signer_name
        request.save(update_fields=["status", "decided_at", "signer_name"])
        _notify_author(request, f"Подписан: {label}", f"Подписал {signer_name}. Код проверки {code}.")
        logger.info("eds.signing.decided: %s #%s подписан (%s)", kind, object_id, code)
        return Outcome(True, f"{kind}_signed")
