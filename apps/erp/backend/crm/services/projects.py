"""Проекты (SPEC-v3 §2.1, §7.3 «Все проекты»): сделки с принятым КП и их документы — договор, счета, акт, исполнение.

«Проект» — не отдельная таблица, а срез сделки (`Deal` от `CONTRACT_SIGNED`): ПР-номер наследует номер заявки, шаг
пути (`CONTRACT` → `PAYMENT` → `DONE`) и статус для клиента (`client-statuses.yaml`) выводятся из документов. Читает
только сотрудник компании-владельца (или администратор): покупателей и посторонних в ERP нет (FIX-13). Действия по
документам ведут свои сервисы (`contract_flow`, `act_flow`, `billing`); здесь — чтение и перечень доступных действий,
которые считает СЕРВЕР по статусу и правам зрителя (страница не угадывает).

«Выполнено» (`project_is_done`): акт подписан (скан), все не отменённые и не черновые счета оплачены, счёт есть. В отличие от
`deal_execution_is_complete` (старый флаг сделки) приёмка поставки клиентом не требуется: в процессе v3 её заменяет акт.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from ..constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from ..models import ActivityLog, Deal
from . import act_flow, contract_flow

#: Сделки-проекты: КП принято клиентом (FSM `CONTRACT_SIGNED`) и дальше. Проигранные в срез не входят.
PROJECT_STAGES = (DealStageCode.CONTRACT_SIGNED, DealStageCode.CLOSED_WON)
#: Сколько проектов просматривается за один запрос (срез в памяти: фильтры «шаг» и «с проблемами» выводятся из документов).
SCAN_LIMIT = 1000
STEPS = ("CONTRACT", "PAYMENT", "DONE")
#: События журнала, которые показываются в истории документов проекта.
JOURNAL_PREFIXES = ("contract.", "act.", "invoice.", "project.", "quote.")


def is_staff_reader(user) -> bool:
    """Читает проекты сотрудник компании-владельца или администратор (`sees_all_deals`)."""
    from accounts.services.permissions import sees_all_deals

    return bool(user and user.is_authenticated and sees_all_deals(user))


def project_queryset() -> QuerySet:
    """Сделки-проекты с документами, подгруженными заранее (список идёт без запроса на каждую сделку)."""
    from integration.services.stages import with_stage_facts

    return with_stage_facts(
        Deal.objects.filter(stage__code__in=PROJECT_STAGES).select_related("manager", "assigned_to", "company")
    ).order_by("-created_at", "-id")


# ── Документы сделки: «живые» и их слова SPEC ───────────────────────────────────────────────────────────


def _live_contract(deal):
    live = [c for c in deal.contracts.all() if c.status_code != ContractStatusCode.CANCELLED]
    return max(live, key=lambda c: c.id) if live else None


def _live_acts(deal) -> list:
    return [a for a in deal.acts.all() if a.status_code != ActStatusCode.CANCELLED]


def _billable_invoices(deal) -> list:
    return [
        i for i in deal.invoices.all() if i.status_code not in (InvoiceStatusCode.CANCELLED, InvoiceStatusCode.DRAFT)
    ]


def _live_invoices(deal) -> list:
    return [i for i in deal.invoices.all() if i.status_code != InvoiceStatusCode.CANCELLED]


def _accepted_quote(deal):
    approved = [q for q in deal.quotes.all() if q.status_id and q.status.code == QuoteStatusCode.APPROVED]
    return max(approved, key=lambda q: q.version) if approved else None


def invoice_word(invoice) -> str:
    """Слово статуса счёта: `to_issue` (черновик, «К выставлению»), `issued`, `partial`, `paid`, `overdue`, `cancelled`."""
    code = invoice.status_code
    if code == InvoiceStatusCode.ISSUED and invoice.due_date and invoice.due_date < timezone.localdate():
        return "overdue"
    return {
        InvoiceStatusCode.DRAFT: "to_issue",
        InvoiceStatusCode.ISSUED: "issued",
        InvoiceStatusCode.PARTIAL: "partial",
        InvoiceStatusCode.PAID: "paid",
        InvoiceStatusCode.OVERDUE: "overdue",
        InvoiceStatusCode.CANCELLED: "cancelled",
    }.get(code, "issued")


def act_word(act) -> str:
    """Слово статуса акта: `project`, `returned` (возвращён с причиной), `issued`, `signed`, `cancelled`."""
    code = act.status_code
    if code == ActStatusCode.DRAFT:
        return "returned" if act.rejection_reason else "project"
    return {ActStatusCode.ISSUED: "issued", ActStatusCode.SIGNED: "signed", ActStatusCode.CANCELLED: "cancelled"}.get(
        code, "project"
    )


# ── Шаг, «Выполнено», статус для клиента, проблемы ──────────────────────────────────────────────────────


def project_is_done(deal) -> bool:
    """Акт подписан и все счета оплачены (SPEC-v3 §2.3 шаг 7); без акта или без счёта проект не выполнен."""
    invoices = _billable_invoices(deal)
    if not invoices or any(i.status_code != InvoiceStatusCode.PAID for i in invoices):
        return False
    acts = _live_acts(deal)
    return bool(acts) and all(a.status_code == ActStatusCode.SIGNED for a in acts)


PROJECT_DONE = "project.done"


@transaction.atomic
def log_project_done_once(deal, actor=None) -> bool:
    """Проект стал «Выполнено» (акт подписан и счета оплачены): ровно одна запись `project.done` в журнале сделки.

    Зовётся из каждого места, где последним может оказаться недостающее условие: скан подписанного акта
    (`act_flow.attach_act_scan`), приёмка акта заказчиком в портале (`billing.sign_act`) и оплата счёта
    (`billing.record_payment`) — порядок «акт, потом оплата» и «оплата, потом акт» даёт один результат. Строка сделки
    берётся под `select_for_update`: две транзакции, каждая из которых записала своё условие, проверяют итог по очереди,
    и вторая видит запись первой; повтор не пишет второй раз. `True` — запись создана сейчас.
    """
    locked = Deal.objects.select_for_update(of=("self",)).get(pk=deal.pk)
    if not project_is_done(locked):
        return False
    if ActivityLog.objects.filter(deal=locked, event_code=PROJECT_DONE).exists():
        return False
    ActivityLog.objects.create(
        action="Проект выполнен",
        detail=f"Сделка #{locked.id}: акт подписан, счета оплачены",
        event_code="project.done",
        event_params={"deal_id": locked.id},
        user=actor,
        level="SUCCESS",
        entity_type="deal",
        entity_id=locked.id,
        deal=locked,
        company_id=locked.company_id,
    )
    return True


def project_step(deal) -> str:
    """Шаг пути для проекта: `DONE`, `PAYMENT` (договор подписан) или `CONTRACT`."""
    if project_is_done(deal):
        return "DONE"
    contract = _live_contract(deal)
    if (contract is not None and contract.status_code == ContractStatusCode.SIGNED) or (
        deal.stage_id and deal.stage.code == DealStageCode.CLOSED_WON
    ):
        return "PAYMENT"
    return "CONTRACT"


def client_status(deal) -> str:
    """Статус для клиента (ключ `packages/contracts/client-statuses.yaml`), SPEC-v3 §2.5."""
    step = project_step(deal)
    if step == "DONE":
        return "done"
    if step == "CONTRACT":
        contract = _live_contract(deal)
        code = contract.status_code if contract else None
        if code in (ContractStatusCode.PENDING_MANAGER, ContractStatusCode.ISSUED_EXTERNAL):
            return "contract_signing"
        return "contract_review"
    if any(a.status_code == ActStatusCode.ISSUED for a in _live_acts(deal)):
        return "awaiting_acceptance"
    if any(i.status_code != InvoiceStatusCode.PAID for i in _billable_invoices(deal)):
        return "awaiting_payment"
    return "fulfilling"


def project_problems(deal) -> list:
    """Что требует внимания: договор отклонён, акт возвращён, счёт просрочен, проект договора не сформирован."""
    problems = []
    contract = _live_contract(deal)
    if contract is None:
        if _accepted_quote(deal) is not None and not any(c for c in deal.contracts.all()):
            problems.append("no_contract")
    elif contract.status_code == ContractStatusCode.REJECTED:
        problems.append("contract_rejected")
    if any(a.status_code == ActStatusCode.DRAFT and a.rejection_reason for a in _live_acts(deal)):
        problems.append("act_returned")
    if any(invoice_word(i) == "overdue" for i in _billable_invoices(deal)):
        problems.append("invoice_overdue")
    return problems


def project_due(deal) -> Optional[datetime.date]:
    """Срок проекта: ожидаемая дата поставки исполнения, иначе самая поздняя дата по строкам поставки."""
    fulfillment = getattr(deal, "fulfillment", None)
    if fulfillment is not None and fulfillment.expected_delivery_date:
        return fulfillment.expected_delivery_date
    dates = [line.eta for line in deal.delivery_lines.all() if line.eta]
    return max(dates) if dates else None


# ── Список ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Filters:
    q: str = ""
    mine: bool = False
    problems: bool = False
    step: str = ""
    deal_id: Optional[int] = None


def _apply_sql_filters(qs: QuerySet, filters: Filters, user) -> QuerySet:
    if filters.deal_id is not None:
        qs = qs.filter(pk=filters.deal_id)
    if filters.mine:
        qs = qs.filter(Q(manager=user) | Q(assigned_to=user))
    text = filters.q.strip()
    if text:
        qs = qs.filter(
            Q(title__icontains=text)
            | Q(company__name__icontains=text)
            | Q(contracts__number__icontains=text)
            | Q(invoices__number__icontains=text)
            | Q(acts__number__icontains=text)
            | Q(quotes__number__icontains=text)
        ).distinct()
    return qs


def list_projects(user, filters: Filters, *, limit: int, offset: int) -> tuple:
    """Страница проектов `(строки, всего)`: SQL-фильтры, затем шаг и «с проблемами» по выведенным значениям."""
    qs = _apply_sql_filters(project_queryset(), filters, user)[:SCAN_LIMIT]
    rows = []
    for deal in qs:
        item = project_row(deal)
        if filters.step and item["step"] != filters.step:
            continue
        if filters.problems and not item["problems"]:
            continue
        rows.append(item)
    return rows[offset : offset + limit], len(rows)


def _money(amount, currency: Optional[str]) -> Optional[dict]:
    if amount is None:
        return None
    return {"amount": f"{Decimal(str(amount)):.2f}", "currency": (currency or "UZS").upper()}


def _quote_ref(quote) -> Optional[dict]:
    if quote is None:
        return None
    return {"id": quote.id, "number": quote.number or "", "status": "accepted", "version": quote.version}


def _contract_ref(contract) -> Optional[dict]:
    if contract is None:
        return None
    return {
        "id": contract.id,
        "number": contract.number,
        "status": contract_flow.contract_v3_status(contract),
        "sent_to_client": contract_flow.contract_sent_to_client(contract),
    }


def _invoices_ref(deal) -> Optional[dict]:
    live = _live_invoices(deal)
    if not live:
        return None
    last = max(live, key=lambda i: i.id)
    return {"id": last.id, "number": last.number, "status": invoice_word(last), "count": len(live)}


def _act_ref(act) -> Optional[dict]:
    if act is None:
        return None
    return {"id": act.id, "number": act.number, "status": act_word(act)}


def _person(user) -> Optional[dict]:
    if user is None:
        return None
    name = (user.get_full_name() or user.email or "").strip()
    return {"id": user.id, "name": name}


def project_row(deal) -> dict:
    """Строка списка проектов: ключевые поля сделки, ссылки на документы, шаг, статус для клиента, проблемы."""
    from integration.services import stages

    quote = _accepted_quote(deal)
    acts = _live_acts(deal)
    act = max(acts, key=lambda a: a.id) if acts else None
    amount = stages.deal_amount(deal)
    return {
        "deal_id": deal.id,
        "title": deal.title or "",
        "company_id": deal.company_id,
        "company_name": deal.company.name if deal.company_id else "",
        "created_at": deal.created_at,
        "step": project_step(deal),
        "client_status": client_status(deal),
        "total": _money(amount, stages.deal_currency(deal)),
        "manager": _person(deal.manager),
        "responsible": _person(deal.assigned_to or deal.manager),
        "due_date": project_due(deal),
        "documents": {
            "quote": _quote_ref(quote),
            "contract": _contract_ref(_live_contract(deal)),
            "invoice": _invoices_ref(deal),
            "act": _act_ref(act),
        },
        "problems": project_problems(deal),
    }


# ── Карточка ───────────────────────────────────────────────────────────────────────────────────────


def _journal(deal, limit: int = 60) -> list:
    """История документов проекта: кто, когда, что сделал и по какой причине (новые первыми)."""
    query = Q()
    for prefix in JOURNAL_PREFIXES:
        query |= Q(event_code__startswith=prefix)
    logs = ActivityLog.objects.filter(query, deal=deal).select_related("user").order_by("-timestamp", "-id")[:limit]
    return [_journal_row(log) for log in logs]


_DOC_BY_PREFIX = {"contract": "contract", "act": "act", "invoice": "invoice", "quote": "quote", "project": "project"}


def _journal_row(log) -> dict:
    params = log.event_params if isinstance(log.event_params, dict) else {}
    return {
        "at": log.timestamp,
        "code": log.event_code,
        "text": log.action,
        "actor_name": (log.user.get_full_name() or log.user.email) if log.user_id else None,
        "document": _DOC_BY_PREFIX.get(log.event_code.split(".")[0]),
        "number": params.get("number"),
        "reason": log.reason or params.get("reason") or params.get("note") or "",
    }


def _history_for(journal: list, kind: str, number: Optional[str]) -> list:
    return [row for row in journal if row["document"] == kind and (number is None or row["number"] in (None, number))]


def _contract_card(contract, user, journal: list) -> Optional[dict]:
    if contract is None:
        return None
    return {
        **_contract_ref(contract),
        "total": _money(contract.total_amount, contract.currency.code if contract.currency_id else None),
        "created_at": contract.created_at,
        "client_agreed_at": contract.client_signed_at,
        "signed_at": contract.manager_signed_at if contract.status_code == ContractStatusCode.SIGNED else None,
        "has_pdf": bool(contract.pdf_file),
        "has_scan": bool(contract.signed_file),
        "actions": contract_flow.allowed_actions(contract, user),
        "history": _history_for(journal, "contract", contract.number),
    }


def _invoice_card(invoice) -> dict:
    return {
        "id": invoice.id,
        "number": invoice.number,
        "status": invoice_word(invoice),
        "total": _money(invoice.total_incl_vat, invoice.currency.code if invoice.currency_id else None),
        "paid": _money(invoice.amount_paid, invoice.currency.code if invoice.currency_id else None),
        "balance_due": _money(invoice.balance_due, invoice.currency.code if invoice.currency_id else None),
        "issued_at": invoice.issued_at,
        "due_date": invoice.due_date,
        "has_pdf": bool(invoice.pdf_file),
    }


def _act_card(act, user, journal: list, deal_currency: str) -> Optional[dict]:
    if act is None:
        return None
    return {
        **_act_ref(act),
        "total": _money(act.total_amount, deal_currency),
        "issued_at": act.issued_at,
        "signed_at": act.signed_at,
        "rejection_reason": act.rejection_reason or "",
        "has_pdf": bool(act.pdf_file),
        "has_scan": bool(act.signed_file),
        "actions": act_flow.allowed_actions(act, user),
        "history": _history_for(journal, "act", act.number),
    }


def _fulfillment_card(deal) -> Optional[dict]:
    fulfillment = getattr(deal, "fulfillment", None)
    if fulfillment is None:
        return None
    status = fulfillment.status
    return {
        "status": status.code if status else None,
        "status_name": status.name if status else None,
        "expected_delivery_date": fulfillment.expected_delivery_date,
        "shipped_at": fulfillment.shipped_at,
        "delivered_at": fulfillment.delivered_at,
        "accepted_at": fulfillment.accepted_at,
        "tracking_number": fulfillment.tracking_number,
        "carrier": fulfillment.carrier,
    }


def _delivery_lines(deal) -> list:
    return [
        {
            "line_no": line.line_no,
            "title": line.title,
            "quantity": line.quantity,
            "unit": line.unit,
            "status": line.status,
            "eta": line.eta,
            "shipped_at": line.shipped_at,
            "tracking": line.tracking,
        }
        for line in deal.delivery_lines.all()
    ]


def _act_blocker(deal, user, acts: list) -> Optional[str]:
    """Почему нельзя выпустить акт сейчас: `no_invoice`, `act_exists`, `forbidden`; `None` — можно."""
    if not act_flow.may_issue_acts(user):
        return "forbidden"
    if acts:
        return "act_exists"
    issuable = (InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.PAID)
    if not any(i.status_code in issuable for i in deal.invoices.all()):
        return "no_invoice"
    return None


def project_card(deal, user) -> dict:
    """Карточка проекта: строка списка плюс документы с историей и действиями, исполнение (только чтение), журнал."""
    row = project_row(deal)
    journal = _journal(deal)
    contract = _live_contract(deal)
    acts = _live_acts(deal)
    act = max(acts, key=lambda a: a.id) if acts else None
    quote = _accepted_quote(deal)
    may_manage = contract_flow.is_staff(user) and contract_flow.may(user, "contract.manage")
    return {
        **row,
        "quote": (
            {**_quote_ref(quote), "outgoing_number": quote.outgoing_number or "", "valid_until": quote.valid_until}
            if quote
            else None
        ),
        "contract": _contract_card(contract, user, journal),
        "can_create_contract": bool(quote and contract is None and may_manage),
        "invoices": [_invoice_card(i) for i in sorted(_live_invoices(deal), key=lambda i: i.id)],
        "act": _act_card(act, user, journal, row["total"]["currency"] if row["total"] else "UZS"),
        "act_blocker": _act_blocker(deal, user, acts),
        "fulfillment": _fulfillment_card(deal),
        "delivery_lines": _delivery_lines(deal),
        "journal": journal,
    }


def project_for_user(user, deal_id: int) -> Optional[Any]:
    """Сделка-проект по id или `None`: чужая и непроектная сделки одинаково «не найдены»."""
    return project_queryset().filter(pk=deal_id).first() if is_staff_reader(user) else None
