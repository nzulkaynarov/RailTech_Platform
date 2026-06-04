from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from ..models import Product, ProductDocument, ProductImage
from ..serializers import ProductDocumentSerializer, ProductImageSerializer, ProductListSerializer, ProductSerializer
from .lookups import LIST_CACHE_TTL


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
                name="stock_status",
                description="Filter by supplier offer stock status code (e.g. IN_STOCK, ON_ORDER)",
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
        tags=["Catalog"],
    ),
    create=extend_schema(summary="Create product", description="Admin only.", tags=["Catalog"]),
    retrieve=extend_schema(
        summary="Get product details",
        description="Returns full product details including offers, images, and documents.",
        tags=["Catalog"],
    ),
    update=extend_schema(summary="Update product", description="Admin only.", tags=["Catalog"]),
    partial_update=extend_schema(summary="Partially update product", tags=["Catalog"]),
    destroy=extend_schema(summary="Delete product", tags=["Catalog"]),
)
@method_decorator(vary_on_headers("Accept-Language", "Authorization"), name="list")
@method_decorator(cache_page(LIST_CACHE_TTL), name="list")
class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD for PIM products.

    Public read access (PUBLISHED only for non-admin);
    write operations require Admin role.
    """

    serializer_class = ProductSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer

    def get_queryset(self):
        user = self.request.user
        base = Product.objects.all().select_related(
            "category", "manufacturer", "domain_type", "status", "uom", "brand", "brand__country"
        )
        if self.action == "list":
            queryset = base.prefetch_related(
                "images",
                "offers__stock_status",
            )
        else:
            queryset = base.prefetch_related(
                "equipment_groups",
                "images",
                "documents",
                "offers__stock_status",
                "offers__supplier",
                "offers__currency",
                "offers__delivery_basis",
            )
        # Non-admins see PUBLISHED + products manufactured by their own company
        if not (user.is_authenticated and user.is_platform_admin):
            from django.db.models import Q

            if user.is_authenticated:
                own_mfg_ids = user.memberships.filter(
                    is_active=True,
                ).values_list("company_id", flat=True)
                queryset = queryset.filter(
                    Q(status__code="PUBLISHED") | Q(manufacturer_id__in=list(own_mfg_ids)),
                )
            else:
                queryset = queryset.filter(status__code="PUBLISHED")

        # Filter by stock_status (from supplier offers)
        stock_status = self.request.query_params.get("stock_status")
        if stock_status:
            queryset = queryset.filter(offers__stock_status__code=stock_status).distinct()

        return queryset

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        "domain_type__code": ["exact"],
        "category": ["exact"],
        "manufacturer": ["exact"],
        "equipment_groups": ["exact"],
    }
    search_fields = ["name", "gost_drawing", "sku"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        if self.action == "bulk_publish":
            from core.permissions import IsPlatformAdmin

            return [permissions.IsAuthenticated(), IsPlatformAdmin()]
        from core.permissions import IsProductManagerOrAdmin

        return [permissions.IsAuthenticated(), IsProductManagerOrAdmin()]

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_platform_admin:
            serializer.save()
            return
        mfg_membership = (
            user.memberships.filter(
                is_active=True,
                company__types__code__in=["MANUFACTURER", "SUPPLIER"],
            )
            .select_related("company")
            .first()
        )
        if not mfg_membership:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("NO_MANUFACTURER_MEMBERSHIP")
        serializer.save(manufacturer=mfg_membership.company)

    @extend_schema(
        summary="Bulk publish products",
        description=(
            "Publish multiple products at once by providing a list of product IDs. "
            "Maximum 500 products per batch. Admin only."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "product_ids": {"type": "array", "items": {"type": "integer"}},
                },
            }
        },
        responses={
            200: OpenApiResponse(description="Products published successfully"),
            400: OpenApiResponse(description="Invalid IDs or batch too large"),
        },
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"])
    def bulk_publish(self, request):
        product_ids = request.data.get("product_ids", [])
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

        from .. import services

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
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiResponse(
                description="XLSX template file"
            ),
        },
        tags=["Catalog"],
    )
    @extend_schema(
        summary="Export products list",
        description="Export filtered product list as CSV or XLSX.",
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="products",
            columns=[
                ("id", "ID", lambda p: p.id),
                ("sku", "SKU", lambda p: p.sku or ""),
                ("name", "Name", lambda p: p.name),
                ("domain_type", "Domain", lambda p: p.domain_type.code if p.domain_type_id else ""),
                ("category", "Category", lambda p: p.category.name if p.category_id else ""),
                ("status", "Status", lambda p: p.status.code if p.status_id else ""),
                ("manufacturer", "Manufacturer", lambda p: p.manufacturer.name if p.manufacturer_id else ""),
                ("created_at", "Created", lambda p: p.created_at.isoformat() if p.created_at else ""),
            ],
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export-template",
        permission_classes=[permissions.IsAuthenticated],
    )
    def export_template(self, request):
        """Generate an XLSX template for catalog import."""
        import openpyxl
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Products"
        headers = [
            "name",
            "sku",
            "description",
            "domain_type",
            "category",
            "uom",
            "manufacturer",
            "gost_drawing",
        ]
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20

        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="railtech_import_template.xlsx"'
        wb.save(response)
        return response

    @extend_schema(
        summary="Upload product image",
        description="Attach an image file to a product. Multipart upload.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "format": "binary"},
                    "is_main": {"type": "boolean", "default": False},
                    "alt_text": {"type": "string"},
                },
            }
        },
        responses={201: ProductImageSerializer},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-image",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get("image")
        if not image_file:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_image_upload

        try:
            validate_image_upload(image_file)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        is_main = str(request.data.get("is_main", "false")).lower() in ("true", "1")
        alt_text = request.data.get("alt_text", "")

        if is_main:
            ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)

        img = ProductImage.objects.create(
            product=product,
            image=image_file,
            is_main=is_main,
            alt_text=alt_text,
        )
        return Response(ProductImageSerializer(img).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete product image",
        responses={204: None, 404: OpenApiResponse(description="Image not found")},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="delete-image/(?P<image_id>[0-9]+)",
        url_name="delete-image",
    )
    def delete_image(self, request, pk=None, image_id=None):
        product = self.get_object()
        img = ProductImage.objects.filter(pk=image_id, product=product).first()
        if not img:
            return Response({"detail": "IMAGE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if img.image:
            img.image.delete(save=False)
        img.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Upload product document",
        description="Attach a technical document (PDF, DOCX) to a product.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "name": {"type": "string"},
                },
            }
        },
        responses={201: ProductDocumentSerializer},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-document",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_document(self, request, pk=None):
        product = self.get_object()
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_document_upload

        try:
            validate_document_upload(file_obj)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        name = request.data.get("name") or file_obj.name
        doc = ProductDocument.objects.create(product=product, file=file_obj, name=name)
        return Response(ProductDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete product document",
        responses={204: None, 404: OpenApiResponse(description="Document not found")},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="delete-document/(?P<doc_id>[0-9]+)",
        url_name="delete-document",
    )
    def delete_document(self, request, pk=None, doc_id=None):
        product = self.get_object()
        doc = ProductDocument.objects.filter(pk=doc_id, product=product).first()
        if not doc:
            return Response({"detail": "DOCUMENT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
