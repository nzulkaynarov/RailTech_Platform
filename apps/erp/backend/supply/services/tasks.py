"""Supply officer's to-do list (plan 0.7, FR-6): what the «Tasks» screen shows besides overdue orders.

One row per action the officer owes, oldest first:

* ``send_order`` — a draft order to a partner (created by hand or from a project shortage) is not sent yet;
* ``partner_date_change`` — the partner asks to move the expected date of a confirmed order;
* ``receive_goods`` — the partner reported a shipment that was not received after it;
* ``partner_application`` — a partnership application waits for the contract or the approval.

ERP decides what is owed; the BFF only shows it. Overdue orders stay in `/stock/overdue/`.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Max, OuterRef, Subquery
from inventory.access import require_supply
from parties.models import PartnerApplication, PartnerApplicationStatus
from supply.models import OrderStatus, SupplierOrder, SupplierOrderShipmentNotice

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


def supply_tasks(user) -> list[dict]:
    """Rows of the supply officer's to-do list; only a holder of `supply.manage` gets them."""
    require_supply(user)
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

    rows.sort(key=lambda row: (row["since"] or "", row["kind"], row["id"]))
    return rows[:MAX_ROWS]
