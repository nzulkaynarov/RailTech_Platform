from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Product, EquipmentGroup, Category, SupplierOffer
from .serializers import (
    ProductSerializer, EquipmentGroupSerializer,
    CategorySerializer, SupplierOfferSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters


class EquipmentGroupViewSet(viewsets.ModelViewSet):
    queryset = EquipmentGroup.objects.all()
    serializer_class = EquipmentGroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        from core.permissions import IsAdminUser
        return [permissions.IsAuthenticated(), IsAdminUser()]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
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


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Product.objects.all().select_related(
            'category', 'manufacturer', 'domain_type', 'status'
        ).prefetch_related('offers', 'images', 'documents')
        # Non-admins only see PUBLISHED products
        # Note: In V2, status is a ForeignKey to ProductStatus, but we filter by its code
        if not (user.is_authenticated and (user.is_superuser or user.is_manager_or_admin)):
            queryset = queryset.filter(status__code='PUBLISHED')
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

    @action(detail=False, methods=['post'])
    def bulk_publish(self, request):
        product_ids = request.data.get('product_ids', [])
        if not product_ids:
            return Response({"error": "No product IDs provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate: product_ids must be a list of integers
        if not isinstance(product_ids, list):
            return Response({"error": "product_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            product_ids = [int(pid) for pid in product_ids]
        except (ValueError, TypeError):
            return Response({"error": "product_ids must contain valid integers"}, status=status.HTTP_400_BAD_REQUEST)

        # Cap batch size to prevent abuse
        if len(product_ids) > 500:
            return Response({"error": "Maximum 500 products per batch"}, status=status.HTTP_400_BAD_REQUEST)

        from .models import ProductStatus
        pub_status = ProductStatus.objects.filter(code='PUBLISHED').first()
        if not pub_status:
            return Response(
                {"error": "PUBLISHED status not found in Master Data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Only publish DRAFT products (prevent re-publishing ARCHIVED etc.)
        updated = Product.objects.filter(
            id__in=product_ids, status__code='DRAFT'
        ).update(status=pub_status)
        return Response({"message": f"Successfully published {updated} products."}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='export-template')
    def export_template(self, request):
        """Generate an XLSX template for catalog import."""
        import openpyxl
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Products'
        headers = ['name', 'sku', 'description', 'domain_type', 'category', 'uom', 'manufacturer', 'gost_drawing']
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="railtech_import_template.xlsx"'
        wb.save(response)
        return response


class SupplierOfferViewSet(viewsets.ModelViewSet):
    queryset = SupplierOffer.objects.all()
    serializer_class = SupplierOfferSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['product', 'supplier', 'stock_status']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        # Write operations require staff-level access
        from core.permissions import IsManagerOrAdmin
        return [permissions.IsAuthenticated(), IsManagerOrAdmin()]


class ManufacturerViewSet(viewsets.ReadOnlyModelViewSet):
    from accounts.serializers import CompanySerializer
    serializer_class = CompanySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        from accounts.models import Company
        manufacturer_ids = Product.objects.exclude(
            manufacturer__isnull=True
        ).values_list('manufacturer_id', flat=True).distinct()
        return Company.objects.filter(id__in=manufacturer_ids).order_by('name')
