"""Counterparty relationship edges — creation + rollups (Phase B, Rule 8 service).

Edges are created lazily at the moments companies actually interact (RFQ routing, offline-client
creation, lead conversion) and touched on every subsequent interaction. Rollups are denormalized
on the edge for the book's list view; `recompute_relationship_rollups` (command) rebuilds them
from scratch when in doubt.
"""

import logging
from typing import Optional

from django.db import models, transaction
from django.utils import timezone

from ..constants import DealStageCode, QuoteStatusCode
from ..models import CounterpartyRelationship, Deal, Quote, RelationshipDirection, RelationshipSource, RelationshipStage

logger = logging.getLogger(__name__)


def touch_relationship(
    *,
    owner_company_id: int,
    counterparty_company_id: int,
    direction: str,
    source: str = RelationshipSource.INBOUND_RFQ,
    owner_member=None,
    when=None,
) -> Optional[CounterpartyRelationship]:
    """Idempotently ensure the edge exists and bump its interaction timestamps.

    Self-edges are refused (a company is not its own counterparty). `source` is only set at
    creation — the FIRST way the relationship appeared is the analytically interesting one.
    """
    if not owner_company_id or not counterparty_company_id or owner_company_id == counterparty_company_id:
        return None
    now = when or timezone.now()
    edge, created = CounterpartyRelationship.objects.get_or_create(
        owner_company_id=owner_company_id,
        counterparty_company_id=counterparty_company_id,
        direction=direction,
        defaults={
            "source": source,
            "first_interaction_at": now,
            "last_interaction_at": now,
            "owner_member": owner_member,
        },
    )
    if not created:
        update_fields = []
        if edge.first_interaction_at is None:
            edge.first_interaction_at = now
            update_fields.append("first_interaction_at")
        if edge.last_interaction_at is None or edge.last_interaction_at < now:
            edge.last_interaction_at = now
            update_fields.append("last_interaction_at")
        # A dormant/prospect edge that interacts again is active; a LOST verdict is explicit
        # (set by a human) and is NOT resurrected automatically.
        if edge.stage in (RelationshipStage.PROSPECT, RelationshipStage.DORMANT):
            edge.stage = RelationshipStage.ACTIVE
            update_fields.append("stage")
        if update_fields:
            edge.save(update_fields=update_fields + ["updated_at"])
    return edge


def ensure_edges_for_deal_routing(deal: Deal, seller_company_ids) -> None:
    """Both sides of an RFQ routing get their edge: the buyer gains a SUPPLIER, each routed
    seller gains a CLIENT. Called from route_request_to_sellers."""
    for seller_company_id in seller_company_ids:
        touch_relationship(
            owner_company_id=deal.company_id,
            counterparty_company_id=seller_company_id,
            direction=RelationshipDirection.SUPPLIER,
            source=RelationshipSource.INBOUND_RFQ,
        )
        touch_relationship(
            owner_company_id=seller_company_id,
            counterparty_company_id=deal.company_id,
            direction=RelationshipDirection.CLIENT,
            source=RelationshipSource.INBOUND_RFQ,
        )


@transaction.atomic
def recompute_rollups_for_edge(edge: CounterpartyRelationship) -> CounterpartyRelationship:
    """Rebuild the denormalized deal rollups of one edge from the source tables.

    The deal set of an edge is direction-aware:
    - CLIENT edge (owner is a seller): deals OF the counterparty routed TO the owner.
    - SUPPLIER edge (owner is a buyer): the owner's own deals routed to the counterparty.
    Either way that is: deal.company = client-side company, routing → seller-side company.
    GMV counts the seller's own quotes on won deals (APPROVED, then any SENT fallback is NOT
    counted — an unaccepted КП is not revenue).
    """
    if edge.direction == RelationshipDirection.CLIENT:
        client_company_id, seller_company_id = edge.counterparty_company_id, edge.owner_company_id
    else:
        client_company_id, seller_company_id = edge.owner_company_id, edge.counterparty_company_id

    deals = Deal.objects.filter(company_id=client_company_id, seller_routings__seller_company_id=seller_company_id)
    won = deals.filter(stage__code=DealStageCode.CLOSED_WON)
    gmv = (
        Quote.objects.filter(
            deal__in=won,
            seller_company_id=seller_company_id,
            status__code=QuoteStatusCode.APPROVED,
        ).aggregate(total=models.Sum("total_incl_vat"))["total"]
        or 0
    )
    edge.deals_count = deals.count()
    edge.won_count = won.count()
    edge.gmv = gmv
    edge.save(update_fields=["deals_count", "won_count", "gmv", "updated_at"])
    return edge


def recompute_rollups_for_deal(deal: Deal) -> None:
    """Refresh rollups on every edge this deal belongs to (both directions of every routed pair).
    Called after deal-stage transitions — cheap: a deal has few routed sellers."""
    seller_ids = list(deal.seller_routings.values_list("seller_company_id", flat=True))
    if not seller_ids:
        return
    edges = CounterpartyRelationship.objects.filter(
        models.Q(owner_company_id=deal.company_id, counterparty_company_id__in=seller_ids)
        | models.Q(owner_company_id__in=seller_ids, counterparty_company_id=deal.company_id)
    )
    for edge in edges:
        recompute_rollups_for_edge(edge)
