from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, throttling, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin
from crm import services as crm_services
from crm.models import ActivityLog, Lead
from crm.serializers import LeadSerializer


class LeadSubmitThrottle(throttling.SimpleRateThrottle):
    scope = "lead_submit"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


@extend_schema(
    summary="Submit lead",
    description=("Submit a lead from the landing page. " "No authentication required. Rate-limited."),
    request=LeadSerializer,
    responses={
        201: LeadSerializer,
        400: OpenApiResponse(description="Validation error"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    tags=["CRM"],
)
class LeadCreateView(APIView):
    """Public endpoint for lead submission from the landing page."""

    permission_classes = []
    throttle_classes = [LeadSubmitThrottle]

    def post(self, request):
        serializer = LeadSerializer(data=request.data)
        if serializer.is_valid():
            lead = serializer.save()
            ActivityLog.objects.create(
                action="Новый лид с сайта",
                detail=(f"Получен запрос от {lead.name} ({lead.email}) " f"через лендинг."),
                level="SUCCESS",
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(summary="List leads", tags=["CRM"]),
    create=extend_schema(summary="Create lead", tags=["CRM"]),
    retrieve=extend_schema(summary="Get lead details", tags=["CRM"]),
    update=extend_schema(summary="Update lead", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update lead", tags=["CRM"]),
    destroy=extend_schema(summary="Delete lead", tags=["CRM"]),
)
class LeadViewSet(viewsets.ModelViewSet):
    """Manager/admin CRUD for leads + convert-to-deal."""

    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    queryset = Lead.objects.all().order_by("-created_at")

    @extend_schema(
        summary="Convert lead to deal",
        tags=["CRM"],
        request=inline_serializer(
            "ConvertLead",
            fields={
                "company_id": drf_serializers.IntegerField(required=False),
            },
        ),
    )
    @action(detail=True, methods=["post"], url_path="convert")
    def convert(self, request, pk=None):
        from accounts.models import Company

        lead = self.get_object()
        company = None
        if request.data.get("company_id"):
            company = Company.objects.filter(pk=request.data["company_id"]).first()
        deal, err = crm_services.convert_lead_to_deal(lead, request.user, company=company)
        if err:
            return Response({"detail": err}, status=400)
        return Response({"deal_id": deal.id, "stage": deal.stage.code if deal.stage else None}, status=201)
