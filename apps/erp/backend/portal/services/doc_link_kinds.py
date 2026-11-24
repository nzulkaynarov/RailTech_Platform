"""Что ссылка документа знает о каждом виде документа (ДК-3, ADR-0030): КП, договор, счёт, акт.

Ссылка (`portal.services.doc_links`) одна для всех видов; здесь — то, что у видов разное: где лежит документ, виден ли он
клиенту, в каком он состоянии, что гость может с ним сделать, какой модуль кабинета открыт для действия и что показать.
Состояние и видимость выводятся из фактов самого документа (статус, срок), а не из ссылки.

Права не расширяются видом: действие выполняет сессия контакта через те же сервисы, что и экран кабинета (`sign_contract_by_client`,
`sign_act`, `reject_act`, принятие КП), и модуль кабинета у каждого вида свой — ссылка договора не открывает действий над КП.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from django.utils import timezone
from portal import projections
from portal.exceptions import PortalConflict
from portal.services import projections_link

#: Ссылка живёт столько дней после срока документа (ADR-0030 п. 6); у документа без срока — `FALLBACK_DAYS` от выпуска.
GRACE_DAYS = 30
FALLBACK_DAYS = 90


class KindSpec:
    kind: str
    #: Модуль кабинета, которому открыто действие над этим видом.
    module: str
    #: Что контакт может сделать с документом по ссылке (кроме «открыть кабинет»).
    actions: tuple[str, ...] = ()
    select_related: tuple[str, ...] = ()

    # Что за документ ------------------------------------------------------------------------------------------------
    def deal(self, doc):
        return doc.deal

    def number(self, doc) -> str:
        return doc.number or ""

    def seller_name(self, doc) -> str:
        raise NotImplementedError

    def currency_code(self, doc) -> str:
        raise NotImplementedError

    def total(self, doc):
        raise NotImplementedError

    # Жизнь документа ------------------------------------------------------------------------------------------------
    def visible(self, doc) -> bool:
        """Документ показывается клиенту; иначе ссылка называет причину «отозвана»."""
        raise NotImplementedError

    def superseded(self, doc) -> bool:
        return False

    def state(self, doc) -> str:
        """`open` — ждёт ответа; иначе итог (`accepted`, `rejected`, `expired`, `paid`)."""
        raise NotImplementedError

    def expiry(self, doc) -> datetime:
        return timezone.now() + timedelta(days=FALLBACK_DAYS)

    # Что можно сделать ---------------------------------------------------------------------------------------------
    def assert_actionable(self, doc) -> None:
        """409, если документ уже решён."""

    def perform(self, doc, action: str, *, contact, text: str, ip: str) -> None:
        raise NotImplementedError

    # PDF и состав --------------------------------------------------------------------------------------------------
    def pdf_file(self, doc):
        """PDF, который можно отдать клиенту; `None` — нет или устарел (проект вместо выпущенного): нужен рендер."""
        return doc.pdf_file or None

    def _fresh_pdf(self, doc, is_draft):
        from crm.services.documents import pdf_is_stale

        if not doc.pdf_file or pdf_is_stale(self.kind, doc.pk, doc.pdf_file, is_draft(doc)):
            return None
        return doc.pdf_file

    def render_pdf_task(self) -> str:
        return self.kind

    def extra(self, doc) -> dict:
        """Поля вида в ответе: срок, оплата, подпись — только клиентская проекция."""
        return {}


class QuoteSpec(KindSpec):
    kind = "quote"
    module = "quotes"
    actions = ("accept", "reject", "question")
    select_related = ("quote__deal__company", "quote__status", "quote__seller_company", "quote__quote_currency")

    def number(self, doc) -> str:
        return projections.quote_number(doc)

    def seller_name(self, doc) -> str:
        return getattr(doc.seller_company, "name", "") or ""

    def currency_code(self, doc) -> str:
        return projections.currency_code(doc.quote_currency)

    def total(self, doc):
        return doc.total_incl_vat

    def visible(self, doc) -> bool:
        return doc.frozen_at is not None  # КП вернули в черновик: клиенту оно больше не показывается

    def superseded(self, doc) -> bool:
        return projections_link.newer_sent_version(doc) is not None

    def state(self, doc) -> str:
        return projections_link.document_state(doc)

    def expiry(self, doc) -> datetime:
        if doc.valid_until:
            return timezone.make_aware(datetime.combine(doc.valid_until + timedelta(days=GRACE_DAYS), time.max))
        return super().expiry(doc)

    def assert_actionable(self, doc) -> None:
        from portal.views import _assert_quote_awaits_decision

        _assert_quote_awaits_decision(doc)

    def perform(self, doc, action, *, contact, text, ip) -> None:
        from portal.services.client_feedback import add_quote_comment
        from portal.views_doclinks import accept_quote, reject_quote

        if action == "accept":
            accept_quote(doc, contact, ip)
        elif action == "reject":
            reject_quote(doc, contact, text, ip)
        else:
            add_quote_comment(doc, contact, text)

    def extra(self, doc) -> dict:
        return {"valid_until": doc.valid_until.isoformat() if doc.valid_until else None}


class ContractSpec(KindSpec):
    kind = "contract"
    module = "contracts"
    actions = ("accept",)
    select_related = ("contract__deal__company", "contract__status", "contract__currency", "contract__quote")

    def seller_name(self, doc) -> str:
        from crm.services.quotes import _quote_seller_company

        seller = _quote_seller_company(doc.quote) if doc.quote_id else None
        return getattr(seller, "name", "") or ""

    def currency_code(self, doc) -> str:
        return projections.currency_code(doc.currency)

    def total(self, doc):
        return doc.total_amount

    def visible(self, doc) -> bool:
        return projections.client_contracts_visible(doc)  # черновик, отклонённый и отменённый — клиенту не показываются

    def state(self, doc) -> str:
        return "open" if projections.contract_status(doc) in ("sent", "signed_by_company") else "accepted"

    def assert_actionable(self, doc) -> None:
        if self.state(doc) != "open":
            raise PortalConflict("CONTRACT_FINALIZED")

    def perform(self, doc, action, *, contact, text, ip) -> None:
        from rest_framework.exceptions import PermissionDenied

        from crm.services.contracts import sign_contract_by_client

        _, error = sign_contract_by_client(doc.pk, portal_contact=contact)
        if error == "CONTRACT_CLIENT_SIGN_NOT_ALLOWED":
            raise PortalConflict("CONTRACT_FINALIZED")
        if error:
            raise PermissionDenied("FORBIDDEN")

    def pdf_file(self, doc):
        from crm.services.documents import contract_is_draft

        return self._fresh_pdf(doc, contract_is_draft)

    def extra(self, doc) -> dict:
        return {"signed_at": doc.client_signed_at.isoformat() if doc.client_signed_at else None}


class InvoiceSpec(KindSpec):
    kind = "invoice"
    module = "invoices"
    actions = ()  # ДК-3: реквизиты и «Оплачено?» — справка; нового пути оплаты нет
    select_related = ("invoice__deal__company", "invoice__status", "invoice__currency", "invoice__contract__quote")

    def seller_name(self, doc) -> str:
        from crm.services.billing import _invoice_seller_company

        seller = _invoice_seller_company(doc)
        return getattr(seller, "name", "") or ""

    def currency_code(self, doc) -> str:
        return projections.currency_code(doc.currency)

    def total(self, doc):
        return doc.total_incl_vat

    def visible(self, doc) -> bool:
        return projections.client_invoices_visible(doc) and projections.invoice_status(doc) != "cancelled"

    def state(self, doc) -> str:
        return "paid" if projections.invoice_status(doc) == "paid" else "open"

    def expiry(self, doc) -> datetime:
        due = projections.invoice_due_date(doc)
        now = timezone.now()
        if due is None:
            return super().expiry(doc)
        return max(
            timezone.make_aware(datetime.combine(due + timedelta(days=GRACE_DAYS), time.max)),
            now + timedelta(days=GRACE_DAYS),
        )

    def pdf_file(self, doc):
        from crm.services.documents import invoice_is_draft

        return self._fresh_pdf(doc, invoice_is_draft)

    def extra(self, doc) -> dict:
        from accounts.services.bank_accounts import bank_details_text
        from crm.services.billing import _invoice_seller_company

        code = self.currency_code(doc)
        due = projections.invoice_due_date(doc)
        details = doc.frozen_bank_details or bank_details_text(_invoice_seller_company(doc), code)
        return {
            "due_date": due.isoformat() if due else None,
            "paid": projections.money(doc.amount_paid, code),
            "balance_due": projections.money(doc.balance_due, code),
            "payment_details": details or None,
        }


class ActSpec(KindSpec):
    kind = "act"
    module = "acts"
    actions = ("accept", "reject")
    select_related = ("act__deal__company", "act__status", "act__invoice__currency")

    def seller_name(self, doc) -> str:
        from crm.services.billing import _invoice_seller_company

        invoice = doc.invoice
        seller = _invoice_seller_company(invoice) if invoice is not None else None
        return getattr(seller, "name", "") or ""

    def currency_code(self, doc) -> str:
        invoice = getattr(doc, "invoice", None)
        return projections.currency_code(invoice.currency) if invoice is not None else projections.currency_code(None)

    def total(self, doc):
        return doc.total_amount

    def visible(self, doc) -> bool:
        return projections.client_acts_visible(doc)

    def state(self, doc) -> str:
        return {"issued": "open", "accepted": "accepted", "returned": "rejected"}[projections.act_status(doc)]

    def assert_actionable(self, doc) -> None:
        if self.state(doc) != "open":
            raise PortalConflict("ACT_FINALIZED")

    def perform(self, doc, action, *, contact, text, ip) -> None:
        from rest_framework.exceptions import PermissionDenied

        from crm.services.billing import reject_act, sign_act

        if action == "accept":
            _, error = sign_act(doc.pk, None, None, portal_contact=contact)
        else:
            _, error = reject_act(doc.pk, None, text, portal_contact=contact)
        if error == "ACT_SIGN_NOT_ALLOWED":
            raise PortalConflict("ACT_FINALIZED")
        if error:
            raise PermissionDenied("FORBIDDEN")

    def pdf_file(self, doc):
        from crm.services.documents import act_is_draft

        return self._fresh_pdf(doc, act_is_draft)

    def extra(self, doc) -> dict:
        issued = projections.act_issued_at(doc)
        return {"issued_at": issued.isoformat()}


SPECS: dict[str, KindSpec] = {spec.kind: spec for spec in (QuoteSpec(), ContractSpec(), InvoiceSpec(), ActSpec())}


def spec_of(kind: str) -> KindSpec:
    return SPECS[kind]


def spec_for(link) -> KindSpec:
    return SPECS[link.kind]


def select_related_all() -> list[str]:
    return ["contact", *(path for spec in SPECS.values() for path in spec.select_related)]


def document_company_id(link) -> Optional[int]:
    return spec_for(link).deal(link.document).company_id
