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

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin

# ---------------------------------------------------------------------------
# Triage Queue
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cross-entity search
# ---------------------------------------------------------------------------


@extend_schema(
    summary="Admin cross-entity search",
    description="Fuzzy admin search across companies, users, deals, supplier offers, and support tickets.",
    parameters=[
        OpenApiParameter(name="q", description="Search term (min 2 chars)", required=True, type=str),
        OpenApiParameter(
            name="per_group", description="Results per group (default 5, max 20)", required=False, type=int
        ),
    ],
    responses={200: OpenApiResponse(description="Grouped search results")},
    tags=["Admin"],
)
class AdminSearchView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"q": q, "groups": []})
        try:
            per_group = min(int(request.query_params.get("per_group", 5)), 20)
        except (TypeError, ValueError):
            per_group = 5

        from accounts.models import Company, CustomUser
        from catalog.models import SupplierOffer
        from core.models import SupportTicket
        from crm.models import Deal

        companies = Company.objects.filter(Q(name__icontains=q) | Q(inn__icontains=q) | Q(email__icontains=q)).order_by(
            "name"
        )[:per_group]
        users = CustomUser.objects.filter(
            Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q)
        ).order_by("email")[:per_group]
        deals = (
            Deal.objects.select_related("company", "stage")
            .filter(Q(title__icontains=q) | Q(id__iexact=q if q.isdigit() else ""))
            .order_by("-updated_at")[:per_group]
        )
        offers = (
            SupplierOffer.objects.select_related("product", "supplier")
            .filter(Q(supplier_sku__icontains=q) | Q(product__name__icontains=q))
            .order_by("product__name")[:per_group]
        )
        tickets = (
            SupportTicket.objects.select_related("company")
            .filter(Q(subject__icontains=q) | Q(description__icontains=q))
            .order_by("-created_at")[:per_group]
        )

        groups = []
        if companies:
            groups.append(
                {
                    "type": "company",
                    "label": "companies",
                    "items": [
                        {
                            "id": c.id,
                            "title": c.name,
                            "subtitle": c.inn or c.email or "",
                            "link": f"/admin/companies/{c.id}",
                        }
                        for c in companies
                    ],
                }
            )
        if users:
            groups.append(
                {
                    "type": "user",
                    "label": "users",
                    "items": [
                        {
                            "id": u.id,
                            "title": u.get_full_name() or u.email,
                            "subtitle": u.email,
                            "link": f"/admin/users/{u.id}",
                        }
                        for u in users
                    ],
                }
            )
        if deals:
            groups.append(
                {
                    "type": "deal",
                    "label": "deals",
                    "items": [
                        {
                            "id": d.id,
                            "title": d.title or f"Deal #{d.id}",
                            "subtitle": " · ".join(
                                filter(
                                    None,
                                    [
                                        d.company.name if d.company_id else "",
                                        d.stage.name if d.stage_id else "",
                                    ],
                                )
                            ),
                            "link": f"/admin/deals/{d.id}",
                        }
                        for d in deals
                    ],
                }
            )
        if offers:
            groups.append(
                {
                    "type": "offer",
                    "label": "offers",
                    "items": [
                        {
                            "id": o.id,
                            "title": f'{o.supplier_sku} · {o.product.name if o.product_id else ""}',
                            "subtitle": o.supplier.name if o.supplier_id else "",
                            "link": f"/admin/offers?focus={o.id}",
                        }
                        for o in offers
                    ],
                }
            )
        if tickets:
            groups.append(
                {
                    "type": "support_ticket",
                    "label": "tickets",
                    "items": [
                        {
                            "id": t.id,
                            "title": t.subject,
                            "subtitle": f"{t.get_status_display()} · {t.get_priority_display()}",
                            "link": f"/admin/support?focus={t.id}",
                        }
                        for t in tickets
                    ],
                }
            )
        return Response({"q": q, "groups": groups})
