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

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin

# ---------------------------------------------------------------------------
# Triage Queue
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Entity-scoped activity log
# ---------------------------------------------------------------------------


@extend_schema(
    summary="Entity-scoped activity log",
    description="Returns ActivityLog entries filtered by entity_type + entity_id. "
    "Used by the Timeline tab on admin detail pages.",
    parameters=[
        OpenApiParameter(
            name="entity_type",
            description="Entity code (company, user, deal, subscription, role_application)",
            required=True,
            type=str,
        ),
        OpenApiParameter(name="entity_id", description="Entity primary key", required=True, type=int),
        OpenApiParameter(name="level", description="Filter by severity level", required=False, type=str),
        OpenApiParameter(name="limit", description="Max items (default 100, max 500)", required=False, type=int),
    ],
    responses={200: OpenApiResponse(description="Activity log entries")},
    tags=["Admin"],
)
class AdminActivityView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        entity_type = (request.query_params.get("entity_type") or "").strip()
        entity_id_raw = request.query_params.get("entity_id")
        if not entity_type or not entity_id_raw:
            return Response({"detail": "entity_type and entity_id are required"}, status=400)
        try:
            entity_id = int(entity_id_raw)
        except (TypeError, ValueError):
            return Response({"detail": "entity_id must be integer"}, status=400)

        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        from crm.models import ActivityLog

        qs = (
            ActivityLog.objects.select_related("user")
            .filter(entity_type=entity_type, entity_id=entity_id)
            .order_by("-timestamp")
        )
        level = request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)

        items = [
            {
                "id": log.id,
                "action": log.action,
                "detail": log.detail,
                "level": log.level,
                "reason": log.reason,
                "before_data": log.before_data,
                "after_data": log.after_data,
                "user_id": log.user_id,
                "user_email": log.user.email if log.user else None,
                "user_name": log.user.get_full_name() if log.user else "",
                "timestamp": log.timestamp.isoformat(),
            }
            for log in qs[:limit]
        ]
        return Response(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "count": len(items),
                "items": items,
            }
        )
