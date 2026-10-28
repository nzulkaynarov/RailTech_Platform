from django.db.models import ProtectedError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters, mixins, permissions, viewsets
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from core.permissions import RoleGatedViewMixin

from ..models import Category, DomainType, ProductStatus, StockStatus
from ..serializers import (
    CategorySerializer,
    DomainTypeSerializer,
    ManufacturerSerializer,
    ProductStatusSerializer,
    StockStatusSerializer,
)

LOOKUP_CACHE_TTL = 60 * 10  # 10 min for rarely-changing lookups
LIST_CACHE_TTL = 60  # 1 min for product list (balance freshness vs Neon latency)


@extend_schema_view(
    list=extend_schema(
        summary="List domain types",
        description="Returns all active domain types (e.g. RAILWAY, GENERAL).",
        tags=["Catalog"],
    ),
    retrieve=extend_schema(
        summary="Get domain type",
        description="Returns a single domain type by ID.",
        tags=["Catalog"],
    ),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class DomainTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/catalog/domain-types/ — active domain types from DB."""

    queryset = DomainType.objects.filter(is_active=True)
    serializer_class = DomainTypeSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # Small lookup table — no pagination needed


@extend_schema_view(
    list=extend_schema(
        summary="List categories",
        description=(
            "Returns all product categories. Searchable by name, "
            "filterable by domain_type__code. Public read access."
        ),
        tags=["Catalog"],
    ),
    create=extend_schema(summary="Create category", description="Admin only.", tags=["Catalog"]),
    retrieve=extend_schema(summary="Get category", tags=["Catalog"]),
    update=extend_schema(summary="Update category", tags=["Catalog"]),
    partial_update=extend_schema(summary="Partially update category", tags=["Catalog"]),
    destroy=extend_schema(
        summary="Delete category",
        responses={
            204: None,
            400: OpenApiResponse(description="CATEGORY_HAS_CHILDREN — the subtree is kept; move or delete it first"),
        },
        tags=["Catalog"],
    ),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class CategoryViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """
    CRUD for product categories.

    Public read access; write operations require `settings.edit` or `catalog.manage` (FIX-42: раздел
    «Категории» в Settings Hub открывается по праву каталога, поэтому и запись разрешена его держателям).
    Filterable by domain_type__code. A category with subcategories cannot be deleted (400 CATEGORY_HAS_CHILDREN).
    """

    required_permissions = {
        "create": ("settings.edit", "catalog.manage"),
        "update": ("settings.edit", "catalog.manage"),
        "partial_update": ("settings.edit", "catalog.manage"),
        "destroy": ("settings.edit", "catalog.manage"),
    }

    queryset = Category.objects.select_related("domain_type").all()
    serializer_class = CategorySerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = {
        "domain_type__code": ["exact"],
    }
    search_fields = ["name"]
    # M1-ERP-09: дерево категорий доступно для управления с правом `settings.edit` (или администратор).

    def destroy(self, request, *args, **kwargs):
        # `Category.parent` — PROTECT (FIX-42, F-5): каскад стирал всё поддерево, хотя диалог обещал «подкатегории
        # перейдут на уровень выше». Ветку не трогаем: оператор сам переносит или удаляет подкатегории.
        instance = self.get_object()
        try:
            instance.delete()
        except ProtectedError:
            return Response({"detail": "CATEGORY_HAS_CHILDREN"}, status=400)
        return Response(status=204)

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        from core.permissions import HasRolePermission

        return [permissions.IsAuthenticated(), HasRolePermission()]


class ManufacturerExists(APIException):
    """400 `{"detail": "MANUFACTURER_EXISTS"}`: бренд с таким названием уже есть."""

    status_code = 400


@extend_schema_view(
    list=extend_schema(
        summary="List manufacturers (OEM brands)",
        description=(
            "Returns OEM brands from the `catalog.Manufacturer` reference table — the "
            "canonical source for `Product.brand`. A brand is catalog metadata, not a "
            "platform participant (sellers/clients are the participant roles). "
            "`?include_inactive=1` adds disabled brands — only for a `catalog.manage` holder."
        ),
        tags=["Catalog"],
    ),
    retrieve=extend_schema(summary="Get manufacturer (OEM brand)", tags=["Catalog"]),
    create=extend_schema(
        summary="Add a manufacturer",
        description="Needs `catalog.manage` (D2-3, B-035). The name is unique, case-insensitively.",
        responses={
            201: ManufacturerSerializer,
            400: OpenApiResponse(description="Field errors or MANUFACTURER_EXISTS"),
        },
        tags=["Catalog"],
    ),
    partial_update=extend_schema(
        summary="Edit a manufacturer",
        description="Needs `catalog.manage` (D2-3, B-035). `is_active=false` hides the brand in selectors; brands are not deleted.",
        responses={
            200: ManufacturerSerializer,
            400: OpenApiResponse(description="Field errors or MANUFACTURER_EXISTS"),
        },
        tags=["Catalog"],
    ),
)
class ManufacturerViewSet(
    RoleGatedViewMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """OEM brands (catalog.Manufacturer): public read for the `brand` selector; create/edit — `catalog.manage` (D2-3)."""

    required_permissions = {"create": "catalog.manage", "partial_update": "catalog.manage"}
    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = ManufacturerSerializer
    search_fields = ["name"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        from ..models import Manufacturer

        queryset = Manufacturer.objects.select_related("country").order_by("name")
        if not self._wants_inactive():
            queryset = queryset.filter(is_active=True)
        return queryset

    def _wants_inactive(self) -> bool:
        """Отключённые бренды видит только тот, кто может их править."""
        request = self.request
        if str(request.query_params.get("include_inactive", "")).lower() not in ("1", "true"):
            return False
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import is_seller, staff_has_permission

        return is_seller(user) and staff_has_permission(user, "catalog.manage")

    def _duplicate(self, serializer) -> bool:
        from ..models import Manufacturer

        name = (serializer.validated_data.get("name") or "").strip()
        existing = Manufacturer.objects.filter(name__iexact=name)
        if serializer.instance is not None:
            existing = existing.exclude(pk=serializer.instance.pk)
        return bool(name) and existing.exists()

    def perform_create(self, serializer):
        if self._duplicate(serializer):
            raise ManufacturerExists("MANUFACTURER_EXISTS")
        serializer.save()

    def perform_update(self, serializer):
        if self._duplicate(serializer):
            raise ManufacturerExists("MANUFACTURER_EXISTS")
        serializer.save()


@extend_schema_view(
    list=extend_schema(summary="List product statuses", tags=["Catalog"]),
    retrieve=extend_schema(summary="Get product status", tags=["Catalog"]),
)
class ProductStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductStatus.objects.filter(is_active=True)
    serializer_class = ProductStatusSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List stock statuses", tags=["Catalog"]),
    retrieve=extend_schema(summary="Get stock status", tags=["Catalog"]),
)
class StockStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockStatus.objects.filter(is_active=True)
    serializer_class = StockStatusSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
