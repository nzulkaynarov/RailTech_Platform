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
                event_code="lead.received",
                event_params={"name": lead.name, "email": lead.email},
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
    """Очередь лидов площадки: оператор назначает, компания берёт в работу.

    Эталон — Salesforce Lead Queue + Take Ownership: входящий лид лежит в очереди ПЛОЩАДКИ,
    оператор его квалифицирует и назначает владельцу, а сделку создаёт принимающая сторона
    (она же становится владельцем). Так квалификация остаётся модерацией, а бизнес-объект не
    рождается от лица оператора (ADR-0002).

    Права: до 24-08 класс стоял на голом `IsPlatformAdmin` — любой оператор, включая
    «Поддержку» с одними `*.view`, мог править и УДАЛЯТЬ лиды. Это приведение к уже
    заявленному («только просмотр»), а не новая блокировка. Сырое удаление снято совсем:
    лид закрывают отклонением с причиной, как контакты (`ContactViewSet`).
    """

    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    http_method_names = ["get", "post", "patch", "put", "head", "options"]
    queryset = Lead.objects.select_related("owner_company", "converted_deal").order_by("-created_at")

    #: Что доступно АРЕНДАТОРУ: увидеть назначенные ему лиды и взять их в работу. Скоуп
    #: держит `get_queryset` (по членству), поэтому операторский гейт здесь не нужен — иначе
    #: принять назначенный лид не смог бы никто, кроме оператора, и механика осталась бы
    #: половинчатой. Тот же приём, что `_MEMBER_ALLOWED_ACTIONS` у компаний.
    _MEMBER_ALLOWED_ACTIONS = {"list", "retrieve", "claim"}

    def get_permissions(self):
        if self.action in self._MEMBER_ALLOWED_ACTIONS and not getattr(self.request.user, "is_superuser", False):
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return queryset
        # Член компании видит ТОЛЬКО назначенные ей лиды: очередь площадки — не его дело.
        return queryset.filter(owner_company__members__user=user, owner_company__members__is_active=True).distinct()

    @extend_schema(
        summary="Route a lead to a company (Salesforce lead assignment)",
        description=(
            "Оператор платформы назначает лид компании. Это маршрутизация, а не создание "
            "сделки: сделку создаёт принимающая сторона действием `claim`."
        ),
        tags=["CRM"],
        request=inline_serializer(
            "RouteLead",
            fields={
                "company_id": drf_serializers.IntegerField(),
                "reason": drf_serializers.CharField(),
            },
        ),
        responses={200: LeadSerializer, 400: OpenApiResponse(description="COMPANY_NOT_FOUND / REASON_REQUIRED")},
    )
    @action(detail=True, methods=["post"], url_path="route")
    def route(self, request, pk=None):
        from accounts.models import Company

        company_id = request.data.get("company_id")
        # `.first()` молча проглатывал несуществующий id и уводил в резолв по e-mail —
        # оператор видел «нет компании клиента» вместо «такой компании нет».
        company = Company.objects.filter(pk=company_id).first() if company_id else None
        lead, err = crm_services.route_lead_to_company(
            self.get_object(), request.user, company, reason=request.data.get("reason", "")
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(LeadSerializer(lead).data)

    @extend_schema(
        summary="Reject a lead (spam / duplicate)",
        tags=["CRM"],
        request=inline_serializer("RejectLead", fields={"reason": drf_serializers.CharField()}),
        responses={200: LeadSerializer, 400: OpenApiResponse(description="REASON_REQUIRED")},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        lead, err = crm_services.reject_lead(self.get_object(), request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(LeadSerializer(lead).data)

    @extend_schema(
        summary="Claim a routed lead — the receiving company creates the deal",
        description=(
            "Компания берёт назначенный ей лид в работу. Сделка рождается здесь, и владелец "
            "у неё правильный — компания, а не оператор платформы (ADR-0002)."
        ),
        tags=["CRM"],
        request=None,
        responses={
            201: OpenApiResponse(description="{deal_id, stage}"),
            400: OpenApiResponse(description="LEAD_NOT_YOURS"),
        },
    )
    @action(detail=True, methods=["post"], url_path="claim")
    def claim(self, request, pk=None):
        deal, err = crm_services.claim_lead(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response({"deal_id": deal.id, "stage": deal.stage.code if deal.stage else None}, status=201)
