"""Сквозной поиск ⌘K: CRM — лиды и клиенты, ERP — сделки и документы; группы по модулям.

Каждая группа и каждый результат проходят по матрице ролей «вида» (`platform-rbac.yaml`): что
раздел скрывает, того в поиске нет. Операции поиска сделок в ERP нет (ERP-09), поэтому номер и
название сделки ищутся по новейшим сделкам ERP (docs/QUESTIONS.md, Q-PLT-14-1).
"""

import asyncio
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.models import ObjectRef, SearchGroup, SearchHit, SearchResult
from app.feeds.numbers import (
    STEP_TITLES,
    cyrillic_prefix,
    deal_number,
    deal_ref,
    deal_step,
    deal_title,
    lead_id_of,
    lead_number,
    lead_ref,
    number_query,
    quote_ref,
)
from app.feeds.snapshot import DEALS_PARAMS, DEALS_PATH
from app.feeds.text import join, segment, short
from app.rbac import Access, allows
from app.rbac_generated import ModuleCode

GROUP_LIMIT = 10
HITS_LIMIT = 10
# Документы ERP, которые Платформа умеет открывать: тип -> раздел матрицы, который его показывает.
_DOC_RESOURCE = {
    "quote": "eds.drafts",
    "contract": "eds.projects",
    "invoice": "eds.payments",
    "act": "eds.projects",
}
_DRAFT_STATUSES = frozenset({"DRAFT", "PENDING_TRADE_REVIEW", "PENDING_APPROVAL", "READY_TO_SEND"})


def _lead_hit(lead: dict[str, Any]) -> SearchHit | None:
    if not isinstance(lead.get("id"), int):
        return None
    name = str(lead.get("display_name") or lead_number(lead["id"]))
    return SearchHit(
        object=lead_ref(lead["id"], name),
        title=name,
        subtitle=join(lead_number(lead["id"]), short(lead.get("need_summary"), 80)) or None,
    )


def _client_hit(client: dict[str, Any]) -> SearchHit | None:
    if not isinstance(client.get("id"), int):
        return None
    name = str(client.get("name") or client["id"])
    inn = client.get("inn")
    ref = ObjectRef(
        kind="client",
        number=str(client["id"]),
        title=name,
        path=f"/crm/clients/{segment(str(client['id']))}?panel=open&tab=card",
    )
    return SearchHit(object=ref, title=name, subtitle=f"ИНН {inn}" if inn else None)


def _deal_hit(deal: dict[str, Any]) -> SearchHit:
    ref = deal_ref(deal)
    company = deal.get("company_name")
    return SearchHit(
        object=ref,
        title=deal_number(deal) + " · " + deal_title(deal)
        if deal_title(deal) != deal_number(deal)
        else deal_number(deal),
        subtitle=join(str(company) if company else None, STEP_TITLES[deal_step(deal)]) or None,
    )


# TODO(ERP-09): поиск сделок по номеру, названию и компании — операция ERP; пока ищет BFF.
def _deal_matches(deal: dict[str, Any], needles: tuple[str, ...]) -> bool:
    haystack = (
        deal_number(deal),
        str(deal.get("title") or ""),
        str(deal.get("company_name") or ""),
    )
    return any(needle in part.casefold() for part in haystack for needle in needles)


def _doc_hit(doc: dict[str, Any], deals: dict[int, dict[str, Any]]) -> SearchHit | None:
    kind = doc.get("type")
    label = doc.get("label")
    if kind not in _DOC_RESOURCE or not isinstance(label, str) or not label:
        return None
    deal = deals.get(doc["deal"]) if isinstance(doc.get("deal"), int) else None
    context = deal_title(deal) if deal else None
    if kind == "quote":
        drafting = doc.get("status_code") in _DRAFT_STATUSES
        return SearchHit(
            object=quote_ref({"number": label}, title=context, drafting=drafting),
            title=label,
            subtitle=context,
        )
    if deal is not None:
        project = deal_ref(deal, tab="documents")
        path = project.path
    else:
        path = f"/eds/documents?type={kind}&q={segment(label)}"
    ref = ObjectRef(kind=kind, number=label, title=context, path=path)
    return SearchHit(object=ref, title=label, subtitle=context)


async def search(feed: Feed, access: Access, query: str) -> SearchResult:
    needle = query.strip().casefold()
    # Латинский префикс номера (`ZV-…`, `kp-…`) -> кириллический; запрос как набран ищется в сделках
    # и в документах ERP (номера документов строит схема нумерации ERP, BFF её не перестраивает).
    # `ЗВ-2026-1` для сделок ищется ещё и как `ЗВ-2026-001`: номер сделки составляет BFF.
    typed = cyrillic_prefix(query)
    canonical = number_query(query)
    needles = tuple(dict.fromkeys(n.casefold() for n in (needle, typed, canonical) if n))
    docs_query = typed
    can_leads = allows(access, "crm.leads", "read")
    can_clients = allows(access, "crm.clients", "read")
    can_docs = any(allows(access, res, "read") for res in set(_DOC_RESOURCE.values()))
    can_deals = allows(access, "eds.projects", "read") or can_clients
    lead_id = lead_id_of(query)

    async def leads() -> list[SearchHit]:
        if not can_leads:
            return []
        found, direct = await asyncio.gather(
            feed.get("crm", "/api/v1/leads", {"q": query.strip(), "limit": HITS_LIMIT}),
            feed.get("crm", f"/api/v1/leads/{lead_id}") if lead_id is not None else _none(),
        )
        candidates = ([direct] if isinstance(direct, dict) else []) + rows(found)
        seen: set[int] = set()
        hits: list[SearchHit] = []
        for lead in candidates:
            hit = _lead_hit(lead)
            if hit is not None and lead["id"] not in seen:
                seen.add(lead["id"])
                hits.append(hit)
        return hits

    async def clients() -> list[SearchHit]:
        if not can_clients:
            return []
        payload = await feed.get("crm", "/api/v1/clients", {"q": query.strip()})
        return [h for c in rows(payload) if (h := _client_hit(c)) is not None]

    async def deals_and_docs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        deal_rows, doc_rows = await asyncio.gather(
            feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            if can_deals or can_docs
            else _none(),
            feed.get(
                "erp",
                "/api/v1/crm/analytics/search-documents/",
                {"q": docs_query, "limit": HITS_LIMIT},
            )
            if can_docs
            else _none(),
        )
        return rows(deal_rows), rows(doc_rows)

    lead_hits, client_hits, (all_deals, all_docs) = await asyncio.gather(
        leads(), clients(), deals_and_docs()
    )
    index = {int(d["id"]): d for d in all_deals if isinstance(d.get("id"), int)}
    matching = [d for d in all_deals if isinstance(d.get("id"), int) and _deal_matches(d, needles)]
    requests = [_deal_hit(d) for d in matching if deal_ref(d).kind == "request" and can_clients]
    projects = [
        _deal_hit(d)
        for d in matching
        if deal_ref(d).kind == "project" and allows(access, "eds.projects", "read")
    ]
    documents = [
        h
        for doc in all_docs
        if allows(access, _DOC_RESOURCE.get(str(doc.get("type")), "admin"), "read")
        and (h := _doc_hit(doc, index)) is not None
    ]
    by_module: dict[ModuleCode, list[SearchHit]] = {
        "crm": [*lead_hits, *client_hits, *requests],
        "eds": [*projects, *documents],
    }
    groups = [
        SearchGroup(module=module, items=hits[:GROUP_LIMIT])
        for module, hits in by_module.items()
        if hits
    ]
    return SearchResult(groups=groups, sources=feed.sources)


async def _none() -> None:
    return None
