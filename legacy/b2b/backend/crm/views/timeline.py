"""Counterparty activity timeline (CRM Phase A, spec-remaining-2026-07-07 §2.1/§2.3).

Read-only feed over ActivityLog's new relation links (company / contact / deal): the history a
company user may see about a deal or a counterparty organization. Thin view — scoping helpers do
the isolation work (Rule 8: no business logic here beyond queryset scoping).
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm.audit_display import actor_display_name
from crm.models import ActivityLog, Deal

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


class TimelineEntrySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    def get_user_name(self, obj) -> str:
        return actor_display_name(obj)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "action",
            "detail",
            # Structured event (E1): the client localizes activity.<event_code> with
            # event_params by viewer locale; action/detail stay the RU legacy fallback.
            "event_code",
            "event_params",
            "level",
            "timestamp",
            "user_name",
            "entity_type",
            "entity_id",
            "deal_id",
            "company_id",
            "contact_id",
        ]


@extend_schema(
    summary="Counterparty / deal activity timeline",
    description=(
        "Chronological business events (deal opened, КП sent/accepted/rejected, contract signed, "
        "payments, messages, KYC) linked to a deal or a counterparty company. Pass deal_id OR "
        "company_id. Scoping: a deal timeline needs access to the deal (member of the client "
        "company, routed seller, or platform admin); a company timeline shows a member their own "
        "company's history, while a routed seller sees only events on deals visible to them."
    ),
    parameters=[
        OpenApiParameter(name="deal_id", type=int, location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name="company_id", type=int, location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name="limit", type=int, location=OpenApiParameter.QUERY, required=False),
    ],
    responses={
        200: TimelineEntrySerializer(many=True),
        400: OpenApiResponse(description="Neither deal_id nor company_id given"),
        403: OpenApiResponse(description="No access to the requested deal"),
        404: OpenApiResponse(description="Deal not found"),
    },
    tags=["CRM Timeline"],
)
class TimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        deal_id = self._int_param(request, "deal_id")
        company_id = self._int_param(request, "company_id")
        limit = min(self._int_param(request, "limit") or DEFAULT_LIMIT, MAX_LIMIT)
        if not deal_id and not company_id:
            return Response({"detail": "TIMELINE_SCOPE_REQUIRED"}, status=400)

        if deal_id:
            queryset, error = self._deal_scope(request, deal_id)
        else:
            queryset = self._company_scope(request, company_id)
            error = None
        if error:
            return error

        entries = queryset.select_related("user").order_by("-timestamp")[:limit]
        return Response(TimelineEntrySerializer(entries, many=True).data)

    @staticmethod
    def _int_param(request, name):
        raw = request.query_params.get(name)
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _deal_scope(request, deal_id):
        """Timeline of one deal — same access boundary as the deal chat."""
        from crm.services.messaging import user_can_access_deal_chat

        deal = Deal.objects.filter(pk=deal_id).first()
        if deal is None:
            return None, Response({"detail": "DEAL_NOT_FOUND"}, status=404)
        if not user_can_access_deal_chat(request.user, deal):
            return None, Response({"detail": "MEMBER_REQUIRED_FOR_ACTION"}, status=403)
        logs = ActivityLog.objects.filter(deal_id=deal_id)
        # SEC (audit #4): a routed seller sees only ITS OWN lane's events (+ deal-level/legacy
        # NULL events) — a competitor's КП-sent/accepted history on a shared deal never leaks.
        from django.db.models import Q

        from accounts.services.permissions import seller_acting_company_ids, seller_visible_deal_ids

        user = request.user
        if not getattr(user, "is_platform_admin", False) and seller_visible_deal_ids(user, request) is not None:
            own = seller_acting_company_ids(user, request) or set()
            logs = logs.filter(Q(seller_company_id__in=own) | Q(seller_company__isnull=True))
        return logs, None

    @staticmethod
    def _company_scope(request, company_id):
        """Timeline of a counterparty organization.

        - Platform admin: everything about the company.
        - A member of the company: their own organization's full history.
        - A routed seller: only events on deals they may see (multi-seller confidentiality —
          an empty scope yields an empty list, never an existence oracle).
        """
        from accounts.services.permissions import seller_visible_deal_ids

        user = request.user
        base = ActivityLog.objects.filter(company_id=company_id)
        if getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False):
            return base
        if user.memberships.filter(company_id=company_id, is_active=True).exists():
            return base
        deal_scope = seller_visible_deal_ids(user, request)
        return base.filter(deal_id__in=deal_scope or set())
