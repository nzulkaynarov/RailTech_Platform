"""Роли компании — один источник правды (КОНТР-1б, ADR-0022, ADR-0028).

Компания держит СПИСОК ролей, у каждой своё состояние; роли не сливаются и не угадываются по тому, как компания попала в
систему:

* `client` — состояние `active`, когда компания клиент по фактам (`accounts.services.clients.client_book_q`);
* `partner` — `application` (заявка на подключение рассматривается), `invited`, `active`, `suspended`; плюс вид партнёра
  (`kind`: изготовитель, поставщик, принципал…) — метка, на права не влияет.

Карточка контрагента, список «Контрагенты», «Люди» и блок «Доступ в кабинет» читают роли отсюда. Здесь же — действие «Не клиент»
(`remove_client_role`): компанию завели клиентом по ошибке, сотрудник снимает роль на месте. Заявки, заведённые по ошибке,
закрываются с причиной «Оформлена по ошибке» (остаются в журнале, из открытых списков и очереди уходят), контакты остаются, а
то, что им открыто в кабинете, следует оставшимся ролям. Настоящая история клиента (КП, договоры, счета) не блокирует действие:
она показывается списком, решает сотрудник. Для оболочки ERP — `dry_run=True` возвращает, что изменится; в ответе нет
персональных данных (только числа и номера заявок).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from parties.models import (
    Company,
    CompanyRelationship,
    Contact,
    PartnerApplication,
    PartnerApplicationStatus,
    RelationshipRole,
    RelationshipStatus,
    active_contact_q,
)

from accounts.constants import CompanyTypeCode
from accounts.services.clients import client_book_q
from catalog.desk.audit import record

PENDING_APPLICATION = (
    PartnerApplicationStatus.SUBMITTED,
    PartnerApplicationStatus.CONTRACT_SENT,
    PartnerApplicationStatus.CANDIDATE_AGREED,
)
#: Причина закрытия заявки, заведённой по ошибке (справочник `request-close-reasons`)
MISTAKE_REASON = "ERROR"


def role_states_for(ids) -> dict[int, list[dict[str, Any]]]:
    """Роли пачки компаний: `[{role, state, kind}]`, порядок — клиент, партнёр; пустой список — ролей нет.

    Три запроса на пачку, а не на строку: годится и для списков."""
    ids = list(ids)
    clients = set(Company.objects.filter(client_book_q(), pk__in=ids).values_list("pk", flat=True))
    relationships = {
        rel.company_id: rel
        for rel in CompanyRelationship.objects.filter(company__in=ids, role=RelationshipRole.PARTNER)
        .exclude(status=RelationshipStatus.TERMINATED)
        .order_by("pk")
    }
    pending: dict[int, str] = {}
    for company_id, kind in (
        PartnerApplication.objects.filter(company__in=ids, status__in=PENDING_APPLICATION)
        .order_by("pk")
        .values_list("company_id", "kind")
    ):
        pending[company_id] = kind
    out: dict[int, list[dict[str, Any]]] = {}
    for pk in ids:
        states: list[dict[str, Any]] = []
        if pk in clients:
            states.append({"role": "client", "state": "active", "kind": None})
        rel = relationships.get(pk)
        kind = (rel.kind if rel and rel.kind else None) or pending.get(pk)
        if rel is not None and rel.status in (RelationshipStatus.ACTIVE, RelationshipStatus.SUSPENDED):
            states.append({"role": "partner", "state": rel.status, "kind": kind})
        elif pk in pending:
            states.append({"role": "partner", "state": "application", "kind": kind})
        elif rel is not None:
            states.append({"role": "partner", "state": "invited", "kind": kind})
        out[pk] = states
    return out


def role_states(company: Company) -> list[dict[str, Any]]:
    return role_states_for([company.pk])[company.pk]


def has_role(states: list[dict[str, Any]], role: str) -> bool:
    """Роль «держится»: у партнёра приостановленное отношение ролью не считается (вход закрыт, в списках — «Приостановлен»)."""
    return any(s["role"] == role and s["state"] != "suspended" for s in states)


def cabinet_truth(company: Company) -> dict[str, Any]:
    """Что с кабинетом на самом деле: открыт ли, когда входили, кем (роли) и что видят (раздел)."""
    from portal.services.access import company_access

    roles, _modules = company_access(company.pk)
    contacts = Contact.objects.filter(active_contact_q(), company=company)
    last_login = max((c.last_login_at for c in contacts if c.last_login_at), default=None)
    states = role_states(company)
    partner = next((s for s in states if s["role"] == "partner"), None)
    if "partner" in roles and "client" in roles:
        sees = "both"
    elif "client" in roles:
        sees = "client"
    elif "partner" in roles:
        sees = "application" if partner and partner["state"] == "application" else "partner"
    else:
        sees = "none"
    return {
        "opened": bool(roles),
        "roles": list(roles),
        "sees": sees,
        "last_login_at": last_login,
        "logged_in_contacts": sum(1 for c in contacts if c.last_login_at),
    }


# ── «Не клиент» ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _deals(company: Company):
    from sales.models import Deal

    return Deal.objects.filter(company=company).select_related("stage")


def client_role_plan(company: Company) -> dict[str, Any]:
    """Что сделает «Не клиент» и что в этой компании настоящее. Ничего не меняет, персональных данных нет."""
    from finance.models import Invoice
    from sales.models import Contract, Quote

    from crm.constants import QuoteStatusCode
    from crm.services import calculation

    open_requests, kept_requests = [], []
    for deal in _deals(company).filter(is_project=False).order_by("pk"):
        stage = deal.stage.code if deal.stage_id else "DRAFT"
        if stage not in calculation.CLOSABLE_STAGES:
            continue
        if calculation.quote_sent_to_client(deal):
            kept_requests.append(deal.number or f"#{deal.pk}")
        else:
            open_requests.append(deal.number or f"#{deal.pk}")
    quotes_sent = Quote.objects.filter(
        deal__company=company, status__code__in=(QuoteStatusCode.SENT, QuoteStatusCode.APPROVED)
    ).count()
    history = {
        "quotes_sent": quotes_sent,
        "contracts": Contract.objects.filter(deal__company=company).count(),
        "invoices": Invoice.objects.filter(deal__company=company).count(),
        "projects": _deals(company).filter(is_project=True).count(),
    }
    contacts = Contact.objects.filter(active_contact_q(), company=company)
    states = role_states(company)
    return {
        "company_id": company.pk,
        "is_client": has_role(states, "client"),
        "has_client_type": company.types.filter(code=CompanyTypeCode.CLIENT).exists(),
        "has_crm_link": hasattr(company, "crm_client_mapping"),
        "requests_to_close": open_requests,
        "requests_kept": kept_requests,
        "history": history,
        "has_history": any(history.values()) or bool(kept_requests),
        "contacts": contacts.count(),
        "contacts_with_cabinet": contacts.filter(last_login_at__isnull=False).count(),
        "remaining_roles": [s for s in states if s["role"] != "client"],
    }


def ensure_candidate_entry(company: Company, app: PartnerApplication | None, actor) -> bool:
    """Заявка на подключение партнёром рассматривается, а отношения нет — временный вход кандидата, тот же, что при отправке
    договора (отношение `partner` «приглашён», только обязательные модули): человек видит заявку, а не пустой кабинет.
    Есть отношение (любое) или заявки нет — ничего не делает."""
    if app is None:
        app = PartnerApplication.objects.filter(company=company, status__in=PENDING_APPLICATION).order_by("-pk").first()
    if app is None or CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER).exists():
        return False
    person = actor if getattr(actor, "pk", None) else None
    CompanyRelationship.objects.create(
        company=company,
        role=RelationshipRole.PARTNER,
        kind=app.kind,
        responsible=person,
        invited_by=person,
        invited_at=timezone.now(),
        modules=[],
        contract_number=app.contract_number,
        contract_date=app.contract_date,
        status=RelationshipStatus.INVITED,
    )
    return True


@transaction.atomic
def remove_client_role(company: Company, *, actor=None, dry_run: bool = False) -> dict[str, Any]:
    """«Не клиент»: снять роль клиента, поставленную по ошибке. `dry_run=True` — только отчёт, ничего не меняется.

    Повтор безопасен. Что делает: закрывает открытые заявки без отправленных клиенту КП причиной «Оформлена по ошибке»
    (запись и журнал остаются, из списков и очереди они уходят); снимает тип `CLIENT`; помечает компанию (`client_role_removed_at`:
    связь с клиентом CRM остаётся связью, но клиентом больше не делает); если заявка на подключение партнёром ещё
    рассматривается, а входа нет — оставляет контактам вход кандидата, чтобы они видели «заявка рассматривается». Настоящая
    история (КП, договоры, счета) в ответе (`history`, `requests_kept`) — действие её не блокирует и не стирает."""
    from sales.models import DealCloseReason

    from crm.services import calculation

    company = Company.objects.select_for_update().get(pk=company.pk)
    plan = client_role_plan(company)
    plan["dry_run"] = dry_run
    if dry_run:
        return plan
    closed: list[str] = []
    reason = DealCloseReason.objects.filter(code=MISTAKE_REASON).first()
    already = not plan["is_client"] and not plan["has_client_type"]
    if not already:
        for deal in _deals(company).filter(is_project=False).order_by("pk"):
            stage = deal.stage.code if deal.stage_id else "DRAFT"
            if stage not in calculation.CLOSABLE_STAGES or calculation.quote_sent_to_client(deal):
                continue
            if reason is not None:
                calculation.close_deal_as(deal, actor if getattr(actor, "pk", None) else None, reason)
                closed.append(deal.number or f"#{deal.pk}")
    company.types.remove(*company.types.filter(code=CompanyTypeCode.CLIENT))
    now = timezone.now()
    company.client_role_removed_at = now
    company.client_role_removed_by = actor if getattr(actor, "pk", None) else None
    company.save(update_fields=["client_role_removed_at", "client_role_removed_by"])
    entry = ensure_candidate_entry(company, None, actor)
    record(
        actor,
        entity="company",
        instance=company,
        event="client_role_removed",
        action="Роль «Клиент» снята: компания заведена клиентом по ошибке",
        before={"client": True},
        after={"client": False, "requests_closed": closed, "history": plan["history"], "candidate_entry": entry},
        detail=company.name,
        level="WARNING" if plan["has_history"] else "INFO",
    )
    plan.update(
        dry_run=False,
        requests_closed=closed,
        candidate_entry=entry,
        remaining_roles=[s for s in role_states(company)],
        is_client=False,
    )
    return plan
