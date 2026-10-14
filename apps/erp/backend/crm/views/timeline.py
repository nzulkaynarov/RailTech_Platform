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
        "payments) linked to a deal or a counterparty company. Pass deal_id OR "
        "company_id. Scoping: a deal timeline needs access to the deal (member of the client "
        "company, own-company staff, or administrator); a company timeline shows a member their own "
        "company's history and own-company staff everything about the counterparty."
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
        """Timeline of one deal — same access boundary as the deal itself."""
        from crm.services import user_can_access_deal

        deal = Deal.objects.filter(pk=deal_id).first()
        if deal is None:
            return None, Response({"detail": "DEAL_NOT_FOUND"}, status=404)
        if not user_can_access_deal(request.user, deal):
            return None, Response({"detail": "MEMBER_REQUIRED_FOR_ACTION"}, status=403)
        logs = ActivityLog.objects.filter(deal_id=deal_id)
        return logs, None

    @staticmethod
    def _company_scope(request, company_id):
        """Timeline of a counterparty organization.

        - Administrator and own-company staff (the seller of every deal): everything about it.
        - A member of the company: their own organization's full history.
        - Anyone else: an empty list (never an existence oracle).
        """
        from accounts.services.permissions import sees_all_deals

        user = request.user
        base = ActivityLog.objects.filter(company_id=company_id)
        if sees_all_deals(user):
            return base
        if user.memberships.filter(company_id=company_id, is_active=True).exists():
            return base
        return base.none()
