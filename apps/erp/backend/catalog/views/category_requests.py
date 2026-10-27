"""Эндпоинты заявок на категорию (R6, D7) — тонкие обёртки над `catalog/category_requests.py`.

Продавец: `POST` (подать) и `GET` (свои обращения — чтобы просьба не проваливалась в тишину).
Решение (`approve` / `reject`) — по праву `settings.edit` (его даёт раздел Платформы «Компания», W13-A3,
решение архитектора по Q-W13A3-1) или администратору (`is_superuser`): кто настраивает компанию и ведёт
справочник категорий, тот и рассматривает обращения по нему. Список — обращения своей компании, администратор
видит все, фильтр по статусу.
"""

from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_serializer,
    extend_schema_view,
)
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import RoleGatedViewMixin

from ..category_requests import approve_category_request, reject_category_request, submit_category_request
from ..models import Category, CategoryRequest


# Имя компонента OpenAPI не `CategoryRequest`: так drf-spectacular называет тело запроса к `Category` (разделение
# запроса и ответа), и описание ответов обращений подменялось схемой категории (B-011, D2-0).
@extend_schema_serializer(component_name="CategoryProposal")
class CategoryRequestSerializer(serializers.ModelSerializer):
    """Чтение — вложенные имена, запись — плоские id (конвенция проекта)."""

    company_name = serializers.CharField(source="company.name", read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, default="")
    resulting_category_name = serializers.CharField(source="resulting_category.name", read_only=True, default="")
    requested_by_email = serializers.CharField(source="requested_by.email", read_only=True, default="")
    domain_type_code = serializers.CharField(source="domain_type.code", read_only=True, default="")

    class Meta:
        model = CategoryRequest
        fields = [
            "id",
            "company",
            "company_name",
            "requested_by_email",
            "proposed_name",
            "parent",
            "parent_name",
            "domain_type",
            "domain_type_code",
            "justification",
            # Статус сравнивается по КОДУ (Rule 2) — отображаемого имени в контракте нет.
            "status",
            "resulting_category",
            "resulting_category_name",
            "review_notes",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "company",
            "status",
            "resulting_category",
            "review_notes",
            "reviewed_at",
            "created_at",
        ]


class CategoryRequestReviewSerializer(serializers.Serializer):
    """Тело решения оператора: категория (одобрение) или причина (отказ)."""

    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False)
    reason = serializers.CharField(required=False, allow_blank=True)


_FORBIDDEN = OpenApiResponse(description="ROLE_NOT_PERMITTED (no required permission)")
_NOT_FOUND = OpenApiResponse(description="Not found (or another company's request)")


@extend_schema_view(
    list=extend_schema(
        summary="List category requests",
        description=(
            "Seller: own company's requests. Platform operator: every request, "
            "filterable by `?status=PENDING|APPROVED|REJECTED`."
        ),
        parameters=[
            OpenApiParameter(
                "status",
                str,
                OpenApiParameter.QUERY,
                enum=["PENDING", "APPROVED", "REJECTED"],
                description="Filter by request status (upper-case codes)",
            )
        ],
        tags=["Catalog"],
    ),
    create=extend_schema(
        summary="Request a new catalog category",
        description=(
            "Escape-hatch for the platform-owned taxonomy (Google Merchant Center pattern): "
            "the seller asks for a category instead of creating one. Never a gate — the "
            "product card lives on without it."
        ),
        responses={
            201: CategoryRequestSerializer,
            400: OpenApiResponse(
                description="CATEGORY_REQUEST_NAME_REQUIRED / COMPANY_REQUIRED / CATEGORY_REQUEST_ALREADY_PENDING, "
                "or serializer field errors"
            ),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ROLE_NOT_PERMITTED"),
        },
        tags=["Catalog"],
    ),
    retrieve=extend_schema(
        summary="Get category request", responses={200: CategoryRequestSerializer, 404: _NOT_FOUND}, tags=["Catalog"]
    ),
)
class CategoryRequestViewSet(
    RoleGatedViewMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    required_permissions = {
        "create": "catalog.manage",
        "approve": "settings.edit",
        "reject": "settings.edit",
    }

    serializer_class = CategoryRequestSerializer
    #: Рассматривает тот же оператор, что ведёт справочник (см. CategoryViewSet).

    def get_permissions(self):
        # Право на решение проверяет гейт `required_permissions` (RoleGatedViewMixin) — до поиска объекта.
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CategoryRequest.objects.none()
        user = self.request.user
        queryset = CategoryRequest.objects.select_related(
            "company", "parent", "domain_type", "resulting_category", "requested_by"
        )
        if not user.is_superuser:
            # Многотенантность: обращения ЧУЖИХ компаний участнику не видны.
            company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
            queryset = queryset.filter(Q(company_id__in=company_ids))
        status_code = self.request.query_params.get("status")
        if status_code:
            queryset = queryset.filter(status=status_code)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_row, error = submit_category_request(
            user=request.user,
            proposed_name=serializer.validated_data.get("proposed_name", ""),
            parent=serializer.validated_data.get("parent"),
            domain_type=serializer.validated_data.get("domain_type"),
            justification=serializer.validated_data.get("justification", ""),
        )
        if error:
            code = status.HTTP_403_FORBIDDEN if error == "ADMIN_VIEWER_CANNOT_ACT" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(request_row).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Approve a category request",
        description="Links the request to the category the operator actually created. Needs `settings.edit` or administrator.",
        request=CategoryRequestReviewSerializer,
        responses={
            200: CategoryRequestSerializer,
            400: OpenApiResponse(
                description="CATEGORY_REQUEST_ALREADY_REVIEWED / CATEGORY_REQUIRED, or serializer field errors"
            ),
            403: _FORBIDDEN,
            404: _NOT_FOUND,
        },
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        payload = CategoryRequestReviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        request_row, error = approve_category_request(
            self.get_object(),
            reviewer=request.user,
            category=payload.validated_data.get("category"),
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(request_row).data)

    @extend_schema(
        summary="Reject a category request",
        description="Requires a reason — a refusal without grounds is not reviewable. Needs `settings.edit` or administrator.",
        request=CategoryRequestReviewSerializer,
        responses={
            200: CategoryRequestSerializer,
            400: OpenApiResponse(
                description="CATEGORY_REQUEST_ALREADY_REVIEWED / REASON_REQUIRED, or serializer field errors"
            ),
            403: _FORBIDDEN,
            404: _NOT_FOUND,
        },
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        payload = CategoryRequestReviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        request_row, error = reject_category_request(
            self.get_object(),
            reviewer=request.user,
            reason=payload.validated_data.get("reason", ""),
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(request_row).data)
