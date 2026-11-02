"""Предложения изменений карточки от поставщиков (CAT-1): «Принять» применяет значение, «Отклонить» закрывает строку.

Строки рождает загрузка прайса (`sourcing/catalog_import.py`), когда файл поставщика расходится с чужой или опубликованной
карточкой. Решает сотрудник с `catalog.manage`; решение — в журнале (`catalog.desk.audit`). Значение справочника
(категория, единица, направление) применяется по id, записанному при загрузке: справочник с тех пор мог измениться —
тогда 409 `PROPOSAL_STALE`, а не тихая подмена.
"""

from __future__ import annotations

from django.utils import timezone

from catalog.desk.audit import record
from catalog.desk.items import ItemError
from catalog.models import ProductFieldProposal

TEXT_FIELDS = {"name", "description", "hs_code", "gost_drawing"}


def proposal_row(proposal: ProductFieldProposal) -> dict:
    return {
        "id": proposal.pk,
        "field": proposal.field,
        "current": proposal.current_value,
        "proposed": proposal.proposed_value,
        "supplier": {"id": proposal.supplier_id, "name": proposal.supplier.name} if proposal.supplier_id else None,
        "created_at": proposal.created_at,
    }


def _reference(proposal: ProductFieldProposal):
    from catalog.models import Category, DomainType
    from core.models import UnitOfMeasure

    model = {"category": Category, "uom": UnitOfMeasure, "domain_type": DomainType}[proposal.field]
    value = model.objects.filter(pk=proposal.proposed_ref).first() if proposal.proposed_ref else None
    if value is None:
        raise ItemError("PROPOSAL_STALE", proposal.field)
    return value


def decide(proposal: ProductFieldProposal, accept: bool, actor) -> ProductFieldProposal:
    """Принять или отклонить открытое предложение. Уже решённое — 409 `PROPOSAL_DECIDED`."""
    if proposal.status != ProductFieldProposal.Status.PENDING:
        raise ItemError("PROPOSAL_DECIDED")
    product = proposal.product
    if accept:
        before = getattr(product, proposal.field + ("_id" if proposal.field not in TEXT_FIELDS else ""))
        if proposal.field in TEXT_FIELDS:
            setattr(product, proposal.field, proposal.proposed_value)
        else:
            setattr(product, proposal.field, _reference(proposal))
        product.save()
        if proposal.field == "hs_code":
            from catalog.services import log_hs_code_change

            log_hs_code_change(product, before or "", actor, origin="supplier")
    proposal.status = ProductFieldProposal.Status.ACCEPTED if accept else ProductFieldProposal.Status.REJECTED
    proposal.decided_by = actor if getattr(actor, "is_authenticated", False) else None
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    record(
        actor,
        entity="product_proposal",
        instance=proposal,
        event="accepted" if accept else "rejected",
        action="Изменение карточки от поставщика " + ("принято" if accept else "отклонено"),
        before={"field": proposal.field, "value": proposal.current_value, "status": "pending"},
        after={
            "field": proposal.field,
            "value": proposal.proposed_value if accept else proposal.current_value,
            "status": proposal.status,
        },
        detail=f"{product.name} | {proposal.get_field_display()}",
    )
    return proposal
