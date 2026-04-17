from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiParameter
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from .models import Product, EquipmentGroup, Category, DomainType, SupplierOffer
from .serializers import (
    ProductSerializer, ProductListSerializer, EquipmentGroupSerializer,
    CategorySerializer, DomainTypeSerializer, SupplierOfferSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

LOOKUP_CACHE_TTL = 60 * 10  # 10 min for rarely-changing lookups
LIST_CACHE_TTL = 60  # 1 min for product list (balance freshness vs Neon latency)


@extend_schema_view(
    list=extend_schema(
        summary="List domain types",
        description="Returns all active domain types (e.g. RAILWAY, GENERAL).",
        tags=['Catalog'],
    ),
    retrieve=extend_schema(
        summary="Get domain type",
        description="Returns a single domain type by ID.",
        tags=['Catalog'],
    ),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
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
        tags=['Catalog'],
    ),
    create=extend_schema(
        summary="Create equipment group",
        description="Create a new equipment group. Admin only.",
        tags=['Catalog'],
    ),
    retrieve=extend_schema(summary="Get equipment group", tags=['Catalog']),
    update=extend_schema(summary="Update equipment group", description="Admin only.", tags=['Catalog']),
    partial_update=extend_schema(summary="Partially update equipment group", tags=['Catalog']),
    destroy=extend_schema(summary="Delete equipment group", tags=['Catalog']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class EquipmentGroupViewSet(viewsets.ModelViewSet):
    """
    CRUD for equipment groups (hierarchical classification).

    Public read access; write operations require Admin role.
    """
    queryset = EquipmentGroup.objects.select_related('domain_type').all()
    serializer_class = EquipmentGroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        from core.permissions import IsAdminUser
        return [permissions.IsAuthenticated(), IsAdminUser()]


@extend_schema_view(
    list=extend_schema(
        summary="List categories",
        description=(
            "Returns all product categories. Searchable by name, "
            "filterable by domain_type__code. Public read access."
        ),
        tags=['Catalog'],
    ),
    create=extend_schema(summary="Create category", description="Admin only.", tags=['Catalog']),
    retrieve=extend_schema(summary="Get category", tags=['Catalog']),
    update=extend_schema(summary="Update category", tags=['Catalog']),
    partial_update=extend_schema(summary="Partially update category", tags=['Catalog']),
    destroy=extend_schema(summary="Delete category", tags=['Catalog']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class CategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD for product categories.

    Public read access; write operations require Admin role.
    Filterable by domain_type__code.
    """
    queryset = Category.objects.select_related('domain_type').all()
    serializer_class = CategorySerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = {
        'domain_type__code': ['exact'],
    }
    search_fields = ['name']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        from core.permissions import IsAdminUser
        return [permissions.IsAuthenticated(), IsAdminUser()]


@extend_schema_view(
    list=extend_schema(
        summary="List products",
        description=(
            "Returns products from the PIM catalog. Non-admin users only see PUBLISHED products. "
            "Filterable by domain_type, category, manufacturer, equipment_groups, stock_status. "
            "Searchable by name, GOST/drawing, SKU."
        ),
        parameters=[
            OpenApiParameter(
                name='stock_status',
                description='Filter by supplier offer stock status code (e.g. IN_STOCK, ON_ORDER)',
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
        tags=['Catalog'],
    ),
    create=extend_schema(summary="Create product", description="Admin only.", tags=['Catalog']),
    retrieve=extend_schema(
        summary="Get product details",
        description="Returns full product details including offers, images, and documents.",
        tags=['Catalog'],
    ),
    update=extend_schema(summary="Update product", description="Admin only.", tags=['Catalog']),
    partial_update=extend_schema(summary="Partially update product", tags=['Catalog']),
    destroy=extend_schema(summary="Delete product", tags=['Catalog']),
)
@method_decorator(vary_on_headers('Accept-Language', 'Authorization'), name='list')
@method_decorator(cache_page(LIST_CACHE_TTL), name='list')
class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD for PIM products.

    Public read access (PUBLISHED only for non-admin);
    write operations require Admin role.
    """
    serializer_class = ProductSerializer

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        return ProductSerializer

    def get_queryset(self):
        user = self.request.user
        base = Product.objects.all().select_related(
            'category', 'manufacturer', 'domain_type', 'status', 'uom'
        )
        if self.action == 'list':
            queryset = base.prefetch_related(
                'images',
                'offers__stock_status',
            )
        else:
            queryset = base.prefetch_related(
                'equipment_groups',
                'images',
                'documents',
                'offers__stock_status',
                'offers__supplier',
                'offers__currency',
                'offers__delivery_basis',
            )
        # Non-admins only see PUBLISHED products
        if not (user.is_authenticated and (user.is_superuser or user.is_manager_or_admin)):
            queryset = queryset.filter(status__code='PUBLISHED')

        # Filter by stock_status (from supplier offers)
        stock_status = self.request.query_params.get('stock_status')
        if stock_status:
            queryset = queryset.filter(
                offers__stock_status__code=stock_status
            ).distinct()

        return queryset

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'domain_type__code': ['exact'],
        'category': ['exact'],
        'manufacturer': ['exact'],
        'equipment_groups': ['exact'],
    }
    search_fields = ['name', 'gost_drawing', 'sku']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        from core.permissions import IsAdminUser
        return [permissions.IsAuthenticated(), IsAdminUser()]

    @extend_schema(
        summary="Bulk publish products",
        description=(
            "Publish multiple products at once by providing a list of product IDs. "
            "Maximum 500 products per batch. Admin only."
        ),
        request={'application/json': {'type': 'object', 'properties': {
            'product_ids': {'type': 'array', 'items': {'type': 'integer'}},
        }}},
        responses={
            200: OpenApiResponse(description="Products published successfully"),
            400: OpenApiResponse(description="Invalid IDs or batch too large"),
        },
        tags=['Catalog'],
    )
    @action(detail=False, methods=['post'])
    def bulk_publish(self, request):
        product_ids = request.data.get('product_ids', [])
        if not product_ids:
            return Response(
                {"error": "No product IDs provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(product_ids, list):
            return Response(
                {"error": "product_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product_ids = [int(pid) for pid in product_ids]
        except (ValueError, TypeError):
            return Response(
                {"error": "product_ids must contain valid integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(product_ids) > 500:
            return Response(
                {"error": "Maximum 500 products per batch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from . import services
        products = Product.objects.filter(id__in=product_ids)
        updated, skipped = services.publish_products(products)

        if not updated and skipped:
            return Response(
                {"error": skipped[0] if len(skipped) == 1 else f"Skipped: {', '.join(skipped)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"message": f"Successfully published {updated} products."},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Download import template",
        description="Generate and download an XLSX template for bulk catalog import.",
        responses={
            (200, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
                OpenApiResponse(description="XLSX template file"),
        },
        tags=['Catalog'],
    )
    @action(
        detail=False, methods=['get'], url_path='export-template',
        permission_classes=[permissions.IsAuthenticated],
    )
    def export_template(self, request):
        """Generate an XLSX template for catalog import."""
        import openpyxl
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Products'
        headers = [
            'name', 'sku', 'description', 'domain_type',
            'category', 'uom', 'manufacturer', 'gost_drawing',
        ]
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
            ws.column_dimensions[
                openpyxl.utils.get_column_letter(col)
            ].width = 20

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = (
            'attachment; filename="railtech_import_template.xlsx"'
        )
        wb.save(response)
        return response


@extend_schema_view(
    list=extend_schema(
        summary="List supplier offers",
        description="Returns all supplier offers. Filterable by product, supplier, stock_status.",
        tags=['Catalog'],
    ),
    create=extend_schema(
        summary="Create supplier offer",
        description="Create a new supplier offer. Manager/Admin only.",
        tags=['Catalog'],
    ),
    retrieve=extend_schema(summary="Get supplier offer", tags=['Catalog']),
    update=extend_schema(summary="Update supplier offer", tags=['Catalog']),
    partial_update=extend_schema(summary="Partially update supplier offer", tags=['Catalog']),
    destroy=extend_schema(summary="Delete supplier offer", tags=['Catalog']),
)
class SupplierOfferViewSet(viewsets.ModelViewSet):
    """
    CRUD for supplier offers (pricing, stock, delivery terms).

    Public read access (active only); write operations require Manager/Admin role.
    """
    serializer_class = SupplierOfferSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['product', 'supplier', 'stock_status']

    def get_queryset(self):
        qs = SupplierOffer.objects.select_related(
            'supplier', 'product', 'currency', 'delivery_basis', 'stock_status'
        )
        # Non-admin users only see active offers
        user = self.request.user
        if not (user.is_authenticated and (user.is_superuser or getattr(user, 'is_manager_or_admin', False))):
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        from core.permissions import IsManagerOrAdmin
        return [permissions.IsAuthenticated(), IsManagerOrAdmin()]


@extend_schema_view(
    list=extend_schema(
        summary="List manufacturers",
        description=(
            "Returns companies that have manufactured products. "
            "Derived from Company records linked to products."
        ),
        tags=['Catalog'],
    ),
    retrieve=extend_schema(summary="Get manufacturer", tags=['Catalog']),
)
class ManufacturerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of companies that are manufacturers (have linked products)."""
    from accounts.serializers import CompanySerializer
    serializer_class = CompanySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        from accounts.models import Company
        return Company.objects.filter(
            manufactured_products__isnull=False
        ).distinct().order_by('name')
