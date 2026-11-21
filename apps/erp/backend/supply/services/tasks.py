"""Supply officer's to-do list (plan 0.7, FR-6): what the «Tasks» screen shows besides overdue orders.

One row per action the officer owes, oldest first:

* ``send_order`` — a draft order to a partner (created by hand or from a project shortage) is not sent yet;
* ``partner_date_change`` — the partner asks to move the expected date of a confirmed order;
* ``receive_goods`` — the partner reported a shipment that was not received after it;
* ``partner_application`` — a partnership application waits for the contract or the approval;
* ``order_shortage`` — a project's goods are still not covered (not shipped, not reserved, not ordered): one row per project,
  the note lists «item: quantity» (СЦ-9). The row goes to the goods-zone assignee of the project's calculation task, and
  to every holder of `supply.manage` when the task names nobody;
* ``ship_project`` — goods reserved for a project are waiting for the shipment (СЦ-9); for holders of `fulfillment.manage`.

ERP decides what is owed; the BFF only shows it. Overdue orders stay in `/stock/overdue/`.
"""

from __future__ import annotations

from typing import Any

from django.db.models import F, Max, OuterRef, Subquery, Sum
from inventory.access import StockError, can_manage_fulfillment, can_manage_supply, require_staff
from inventory.services import stock
from parties.models import PartnerApplication, PartnerApplicationStatus
from supply.models import GoodsReceiptLine, OrderStatus, SupplierOrder, SupplierOrderShipmentNotice
from supply.services import shortage

from core.quantity import qty_text

MAX_ROWS = 200

#: Application statuses where the next step is ours: send the contract or approve.
APPLICATION_OPEN = (PartnerApplicationStatus.SUBMITTED, PartnerApplicationStatus.CANDIDATE_AGREED)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _order_row(order: SupplierOrder, kind: str, since, **extra: Any) -> dict:
    return {
        "kind": kind,
        "id": order.pk,
        "number": order.number,
        "supplier_name": order.supplier.name,
        "since": _iso(since),
        **extra,
    }


def _goods_assignees(deal_ids: list[int]) -> dict[int, set[int]]:
    """Project → ERP users who are goods-zone assignees of its latest calculation task (as `visa_assignees`, but for all
    projects at once). A project whose task names nobody resolvable is absent."""
    from sales.models import CalcTask, CalcTaskAssignee

    from crm.models import CalcZone
    from crm.services.calc_tasks import _users_by_crm_id

    task_deal = dict(
        CalcTask.objects.filter(deal_id__in=deal_ids)
        .order_by("deal_id", "-decided_at", "-id")
        .distinct("deal_id")
        .values_list("pk", "deal_id")
    )
    rows = list(
        CalcTaskAssignee.objects.filter(task_id__in=list(task_deal), zone=CalcZone.GOODS).values_list(
            "task_id", "crm_user_id", "user_id"
        )
    )
    found = _users_by_crm_id({crm_id for _task, crm_id, user_id in rows if user_id is None})
    result: dict[int, set[int]] = {}
    for task_id, crm_id, user_id in rows:
        resolved = user_id or found.get(crm_id)
        if resolved:
            result.setdefault(task_deal[task_id], set()).add(resolved)
    return result


def _shortage_rows(user) -> list[dict]:
    """`order_shortage`: one row per project that still has uncovered goods in its last approved quote."""
    from sales.models import Quote

    from crm.constants import QuoteStatusCode
    from crm.services.projects import PROJECT_STAGES

    quotes = list(
        Quote.objects.filter(deal__stage__code__in=PROJECT_STAGES, status__code=QuoteStatusCode.APPROVED)
        .select_related("deal__company", "deal__stage")
        .order_by("deal_id", "-version")
        .distinct("deal_id")
    )
    by_quote = shortage.goods_items(quote.pk for quote in quotes)
    missing = shortage.shortage_by_item([item for items in by_quote.values() for item in items])
    candidates = [quote for quote in quotes if any(item.pk in missing for item in by_quote.get(quote.pk, []))]
    candidates = [quote for quote in candidates if not stock.deal_closed_for_stock(quote.deal)]
    assignees = _goods_assignees([quote.deal_id for quote in candidates])
    rows = []
    for quote in candidates:
        named = assignees.get(quote.deal_id)
        if named and user.pk not in named:
            continue  # somebody is named for this project and it is not the viewer
        lines = [
            f"{item.imported_raw_name or item.product.name}: {qty_text(missing[item.pk])}"
            for item in by_quote[quote.pk]
            if item.pk in missing
        ]
        rows.append(
            {
                "kind": "order_shortage",
                "id": quote.deal_id,
                "number": quote.deal.number,
                "supplier_name": "",
                "client_name": quote.deal.company.name if quote.deal.company_id else "",
                "since": _iso(quote.approved_at or quote.updated_at),
                "note": "; ".join(lines),
            }
        )
    return rows


def _shipment_rows() -> list[dict]:
    """`ship_project`: a project with a fulfillment and an active reservation that is not shipped out yet."""
    from sales.models import Deal

    from crm.services.projects import PROJECT_STAGES

    left = {
        row["deal_id"]: row["left"]
        for row in stock.active_reservations()
        .filter(deal__stage__code__in=PROJECT_STAGES, deal__fulfillment__isnull=False)
        .order_by()
        .values("deal_id")
        .annotate(left=Sum(F("quantity") - F("shipped_quantity")))
        .filter(left__gt=0)
    }
    if not left:
        return []
    last_receipt = {
        row["order_line__deal_id"]: row["last"]
        for row in GoodsReceiptLine.objects.filter(order_line__deal_id__in=list(left))
        .order_by()
        .values("order_line__deal_id")
        .annotate(last=Max("receipt__received_at"))
    }
    rows = []
    for deal in Deal.objects.filter(pk__in=list(left)).select_related("company", "fulfillment", "stage"):
        if stock.deal_closed_for_stock(deal):
            continue
        since = max(filter(None, [last_receipt.get(deal.pk), deal.fulfillment.created_at]))
        rows.append(
            {
                "kind": "ship_project",
                "id": deal.pk,
                "number": deal.number,
                "supplier_name": "",
                "client_name": deal.company.name if deal.company_id else "",
                "since": _iso(since),
                "note": f"в резерве {qty_text(left[deal.pk])}",
            }
        )
    return rows


def supply_tasks(user) -> list[dict]:
    """Rows of the to-do list: supply rows for a holder of `supply.manage`, shipment rows for `fulfillment.manage`;
    neither right — 403."""
    require_staff(user)
    supply, ship = can_manage_supply(user), can_manage_fulfillment(user)
    if not (supply or ship):
        raise StockError("ROLE_NOT_PERMITTED", 403)
    rows: list[dict] = []
    if supply:
        rows.extend(_supply_rows())
        rows.extend(_shortage_rows(user))
    if ship:
        rows.extend(_shipment_rows())
    rows.sort(key=lambda row: (row["since"] or "", row["kind"], row["id"]))
    return rows[:MAX_ROWS]


def _supply_rows() -> list[dict]:
    rows: list[dict] = []
    orders = SupplierOrder.objects.select_related("supplier")

    for order in orders.filter(status=OrderStatus.DRAFT).order_by("created_at", "id")[:MAX_ROWS]:
        rows.append(_order_row(order, "send_order", order.created_at))

    for order in orders.filter(status=OrderStatus.CONFIRMED, partner_requested_date__isnull=False).order_by(
        "partner_requested_at", "id"
    )[:MAX_ROWS]:
        rows.append(
            _order_row(
                order,
                "partner_date_change",
                order.partner_requested_at,
                date=_iso(order.partner_requested_date),
                note=order.partner_requested_reason or None,
            )
        )

    last_notice = SupplierOrderShipmentNotice.objects.filter(order=OuterRef("pk")).order_by("-created_at")
    shipped = (
        orders.filter(status=OrderStatus.CONFIRMED)
        .annotate(
            shipped_at=Max("shipment_notices__created_at"),
            last_receipt_at=Max("receipts__received_at"),
            shipped_doc=Subquery(last_notice.values("supplier_doc")[:1]),
        )
        .filter(shipped_at__isnull=False)
        .order_by("shipped_at", "id")
    )
    for order in shipped[:MAX_ROWS]:
        if order.last_receipt_at is not None and order.last_receipt_at >= order.shipped_at:
            continue  # the shipment was received after the partner reported it
        rows.append(_order_row(order, "receive_goods", order.shipped_at, note=order.shipped_doc or None))

    applications = PartnerApplication.objects.filter(status__in=APPLICATION_OPEN).order_by("created_at", "id")
    for application in applications[:MAX_ROWS]:
        since = (
            application.candidate_agreed_at
            if application.status == PartnerApplicationStatus.CANDIDATE_AGREED
            else application.created_at
        )
        rows.append(
            {
                "kind": "partner_application",
                "id": application.pk,
                "number": None,
                "supplier_name": application.company_name,
                "since": _iso(since),
                "status": application.status,
            }
        )

    return rows
