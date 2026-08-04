from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, permissions, viewsets

from ..models import Category, DomainType, EquipmentGroup, ProductStatus, StockStatus
from ..serializers import (
    CategorySerializer,
    DomainTypeSerializer,
    EquipmentGroupSerializer,
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
        summary="List equipment groups",
        description="Returns all equipment groups. Searchable by name. Public read access.",
        tags=["Catalog"],
    ),
    create=extend_schema(
        summary="Create equipment group",
        description="Create a new equipment group. Admin only.",
        tags=["Catalog"],
    ),
    retrieve=extend_schema(summary="Get equipment group", tags=["Catalog"]),
    update=extend_schema(summary="Update equipment group", description="Admin only.", tags=["Catalog"]),
    partial_update=extend_schema(summary="Partially update equipment group", tags=["Catalog"]),
    destroy=extend_schema(summary="Delete equipment group", tags=["Catalog"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class EquipmentGroupViewSet(viewsets.ModelViewSet):
    """
    CRUD for equipment groups (hierarchical classification).

    Public read access; write operations require an operator with `platform.settings`
    (N3, ADR-0004: раньше писала ЛЮБАЯ суб-роль оператора, включая SUPPORT «только просмотр»).
    """

    # EquipmentGroup has no domain_type FK (only a self-referential `parent`);
    # select_related("domain_type") raised FieldError → 500 on every list.
    queryset = EquipmentGroup.objects.select_related("parent").all()
    serializer_class = EquipmentGroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    operator_permission = "platform.settings"

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        from core.permissions import OperatorScoped

        return [OperatorScoped()]


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
    destroy=extend_schema(summary="Delete category", tags=["Catalog"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class CategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD for product categories.

    Public read access; write operations require Admin role.
    Filterable by domain_type__code.
    """

    queryset = Category.objects.select_related("domain_type").all()
    serializer_class = CategorySerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = {
        "domain_type__code": ["exact"],
    }
    search_fields = ["name"]
    # N3: дерево категорий — «справочники» из ADR-0004; пишет только оператор
    # с `platform.settings`, а не любая суб-роль.
    operator_permission = "platform.settings"

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        from core.permissions import OperatorScoped

        return [OperatorScoped()]


@extend_schema_view(
    list=extend_schema(
        summary="List manufacturers (OEM brands)",
        description=(
            "Returns OEM brands from the `catalog.Manufacturer` reference table — the "
            "canonical source for `Product.brand`. A brand is catalog metadata, not a "
            "platform participant (sellers/buyers are the participant roles)."
        ),
        tags=["Catalog"],
    ),
    retrieve=extend_schema(summary="Get manufacturer (OEM brand)", tags=["Catalog"]),
)
class ManufacturerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of OEM brands (catalog.Manufacturer) for the `brand` selector."""

    serializer_class = ManufacturerSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        from ..models import Manufacturer

        return Manufacturer.objects.filter(is_active=True).select_related("country").order_by("name")


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
