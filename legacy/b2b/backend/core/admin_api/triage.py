"""
Admin Platform API: endpoints consumed exclusively by the React Platform Admin
SPA (PlatformAdminShell). All views require IsPlatformAdmin.

Exposes:
  GET /api/v1/admin/queue/      — unified triage queue (KYC, role apps, billing, tickets)
  GET /api/v1/admin/pulse/      — time-series pulse metrics (companies, deals, MRR)
  GET /api/v1/admin/search/     — cross-entity search (companies, users, deals, tickets, offers)
  GET /api/v1/admin/activity/   — ActivityLog scoped to a single entity

All data is derived from real DB models via ORM. No hardcoded rows, no fakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin

# ---------------------------------------------------------------------------
# Triage Queue
# ---------------------------------------------------------------------------


def _fmt_age(created: datetime | None) -> str:
    if not created:
        return ""
    delta = timezone.now() - created
    if delta.days >= 1:
        return f"{delta.days}d"
    hours = delta.seconds // 3600
    if hours:
        return f"{hours}h"
    minutes = max(1, delta.seconds // 60)
    return f"{minutes}m"


def _queue_kyc() -> list[dict[str, Any]]:
    from accounts.models import Company

    qs = (
        Company.objects.select_related("verification_status")
        .filter(verification_status__code="PROFILE_SUBMITTED")
        .order_by("created_at")
    )
    return [
        {
            "queue_type": "kyc_pending",
            "entity_type": "company",
            "entity_id": c.id,
            "title": c.name or f"Company #{c.id}",
            "subtitle": f"INN {c.inn}" if c.inn else "",
            "severity": "warning",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "age": _fmt_age(c.created_at),
            "actions": ["approve_kyc_l2", "revoke_kyc", "view"],
            "link": f"/admin/companies/{c.id}",
        }
        for c in qs
    ]


def _queue_role_applications() -> list[dict[str, Any]]:
    from accounts.models import CompanyRoleApplication

    qs = (
        CompanyRoleApplication.objects.select_related("company", "requested_type", "submitted_by")
        .filter(status__in=["PENDING", "DOCUMENTS_REQUIRED", "PAYMENT_REQUIRED"])
        .order_by("created_at")
    )
    return [
        {
            "queue_type": "role_application",
            "entity_type": "role_application",
            "entity_id": a.id,
            "title": f"{a.company.name} → {a.requested_type.name}",
            "subtitle": a.get_status_display(),
            "severity": "info" if a.status == "PENDING" else "warning",
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "age": _fmt_age(a.created_at),
            "actions": ["approve_role", "reject_role", "view"],
            "link": f"/admin/role-apps?focus={a.id}",
        }
        for a in qs
    ]


def _queue_subscriptions() -> list[dict[str, Any]]:
    from accounts.models import SupplierSubscription

    now = timezone.now()
    soon = now + timedelta(days=7)
    past_due = SupplierSubscription.objects.select_related("company").filter(status="PAST_DUE").order_by("valid_until")
    expiring = (
        SupplierSubscription.objects.select_related("company")
        .filter(
            status__in=["ACTIVE", "TRIAL"],
            valid_until__isnull=False,
            valid_until__lte=soon.date(),
            valid_until__gte=now.date(),
        )
        .order_by("valid_until")
    )
    items: list[dict[str, Any]] = []
    for s in past_due:
        items.append(
            {
                "queue_type": "subscription_past_due",
                "entity_type": "subscription",
                "entity_id": s.id,
                "title": s.company.name if s.company else f"Subscription #{s.id}",
                "subtitle": f"{s.plan} · past due since {s.valid_until}" if s.valid_until else s.plan,
                "severity": "critical",
                "created_at": s.valid_until.isoformat() if s.valid_until else None,
                "age": (
                    _fmt_age(
                        datetime.combine(s.valid_until, datetime.min.time(), tzinfo=timezone.get_current_timezone())
                    )
                    if s.valid_until
                    else ""
                ),
                "actions": ["activate_subscription", "suspend_subscription", "view"],
                "link": f"/admin/subscriptions?focus={s.id}",
            }
        )
    for s in expiring:
        items.append(
            {
                "queue_type": "subscription_expiring",
                "entity_type": "subscription",
                "entity_id": s.id,
                "title": s.company.name if s.company else f"Subscription #{s.id}",
                "subtitle": f"{s.plan} · expires {s.valid_until}",
                "severity": "warning",
                "created_at": s.valid_until.isoformat() if s.valid_until else None,
                "age": (
                    _fmt_age(
                        datetime.combine(s.valid_until, datetime.min.time(), tzinfo=timezone.get_current_timezone())
                    )
                    if s.valid_until
                    else ""
                ),
                "actions": ["activate_subscription", "view"],
                "link": f"/admin/subscriptions?focus={s.id}",
            }
        )
    return items


def _queue_invoices() -> list[dict[str, Any]]:
    from crm.models import Invoice

    today = timezone.now().date()
    qs = (
        Invoice.objects.select_related("contract", "contract__deal", "contract__deal__company")
        .filter(
            status__in=["ISSUED", "PARTIAL", "OVERDUE"],
            due_date__lt=today,
        )
        .order_by("due_date")
    )
    items: list[dict[str, Any]] = []
    for inv in qs:
        company_name = (
            inv.contract.deal.company.name
            if inv.contract_id and inv.contract.deal_id and inv.contract.deal.company_id
            else ""
        )
        items.append(
            {
                "queue_type": "invoice_overdue",
                "entity_type": "invoice",
                "entity_id": inv.id,
                "title": f"{inv.number} · {company_name}".strip(" ·"),
                "subtitle": f"{inv.total_incl_vat} · due {inv.due_date}",
                "severity": "critical",
                "created_at": inv.due_date.isoformat() if inv.due_date else None,
                "age": (
                    _fmt_age(
                        datetime.combine(inv.due_date, datetime.min.time(), tzinfo=timezone.get_current_timezone())
                    )
                    if inv.due_date
                    else ""
                ),
                "actions": ["view"],
                "link": (
                    f"/admin/deals/{inv.contract.deal_id}"
                    if inv.contract_id and inv.contract.deal_id
                    else "/admin/deals"
                ),
            }
        )
    return items


def _queue_support() -> list[dict[str, Any]]:
    from core.models import SupportTicket

    qs = (
        SupportTicket.objects.select_related("company", "created_by")
        .filter(
            priority__in=[SupportTicket.PRIORITY_HIGH, SupportTicket.PRIORITY_URGENT],
            status__in=[SupportTicket.STATUS_OPEN, SupportTicket.STATUS_IN_PROGRESS],
        )
        .order_by("-priority", "created_at")
    )
    return [
        {
            "queue_type": "support_urgent",
            "entity_type": "support_ticket",
            "entity_id": t.id,
            "title": t.subject,
            "subtitle": f"{t.company.name} · {t.get_priority_display()}" if t.company_id else t.get_priority_display(),
            "severity": "critical" if t.priority == SupportTicket.PRIORITY_URGENT else "warning",
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "age": _fmt_age(t.created_at),
            "actions": ["view"],
            "link": f"/admin/support?focus={t.id}",
        }
        for t in qs
    ]


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@extend_schema(
    summary="Admin triage queue",
    description="Unified list of items requiring platform admin attention: KYC pending, "
    "role applications, subscriptions past-due/expiring, overdue invoices, urgent "
    "support tickets. Sorted by severity then oldest first.",
    parameters=[
        OpenApiParameter(name="queue_type", description="Filter by queue_type code", required=False, type=str),
        OpenApiParameter(name="limit", description="Max items to return (default 200)", required=False, type=int),
    ],
    responses={200: OpenApiResponse(description="Queue items")},
    tags=["Admin"],
)
class AdminTriageQueueView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qt_filter = request.query_params.get("queue_type") or ""
        try:
            limit = min(int(request.query_params.get("limit", 200)), 500)
        except (TypeError, ValueError):
            limit = 200
        collectors = [
            _queue_kyc,
            _queue_role_applications,
            _queue_subscriptions,
            _queue_invoices,
            _queue_support,
        ]
        items: list[dict[str, Any]] = []
        for collect in collectors:
            try:
                items.extend(collect())
            except Exception:  # pragma: no cover — don't let one source break the whole queue
                continue
        if qt_filter:
            items = [i for i in items if i.get("queue_type") == qt_filter]
        items.sort(
            key=lambda i: (
                SEVERITY_ORDER.get(i.get("severity", "info"), 3),
                i.get("created_at") or "",
            )
        )
        totals: dict[str, int] = {}
        for i in items:
            key = i["queue_type"]
            totals[key] = totals.get(key, 0) + 1
        return Response(
            {
                "count": len(items),
                "totals": totals,
                "items": items[:limit],
            }
        )
