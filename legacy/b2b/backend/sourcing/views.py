import base64
import logging

from celery.result import AsyncResult
from django.db import DatabaseError
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from kombu.exceptions import OperationalError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

# IsPlatformAdmin previously required here — now inline member-check covers
# the seller self-serve flow. Keeping the import removed for cleanliness.
from .models import ImportTask
from .tasks import process_catalog_import, process_excel_import

logger = logging.getLogger(__name__)

# Max Excel file size: 20MB
MAX_EXCEL_FILE_SIZE = 20 * 1024 * 1024

# XLSX magic bytes (ZIP/PK header)
XLSX_MAGIC = b"PK\x03\x04"


def _validate_xlsx_signature(file_bytes: bytes) -> bool:
    """Validate that file starts with ZIP/XLSX magic bytes."""
    return file_bytes[:4] == XLSX_MAGIC


def _check_deal_access(user, deal) -> bool:
    """Centralized deal access check to prevent IDOR."""
    if user.is_platform_admin:
        return True
    if deal.manager_id == user.id:
        return True
    if deal.company:
        return user.memberships.filter(company=deal.company, is_active=True).exists()
    return deal.client_id == user.id


@extend_schema(
    summary="Import Excel for deal",
    description=(
        "Upload an XLSX file to import quote items for a specific deal. "
        "Both clients (for own deals) and managers can import. "
        "Max file size: 20MB. Only .xlsx format accepted. "
        "Returns a Celery task_id for polling import status."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary", "description": "XLSX file"},
            },
        }
    },
    responses={
        202: OpenApiResponse(description="Import task queued, task_id returned"),
        400: OpenApiResponse(description="No file, invalid format, or file too large"),
        403: OpenApiResponse(description="No access to this deal"),
        404: OpenApiResponse(description="Deal not found"),
    },
    tags=["Sourcing"],
)
class ExcelImportView(APIView):
    """Endpoint for deal-specific excel imports.
    Both clients (for own deals) and managers can import.
    Deal access is verified inside the view via _check_deal_access.
    """

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import_upload"

    def post(self, request, deal_id):
        from crm.models import Deal

        try:
            deal = Deal.objects.select_related("company").get(pk=deal_id)
        except Deal.DoesNotExist:
            return Response(
                {"error": "Deal not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # IDOR protection: verify deal access
        if not _check_deal_access(request.user, deal):
            return Response({"error": "You do not have access to this deal"}, status=status.HTTP_403_FORBIDDEN)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"error": "No file uploaded"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # File size validation
        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"error": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # AI mode: the client may upload ANY supported file (Excel/CSV/PDF/image/text)
        # and Claude maps it to our schema. Without AI we keep the strict xlsx-only path.
        from django.conf import settings

        use_ai = str(request.data.get("use_ai", "")).strip().lower() in ("true", "1", "yes", "on")
        use_ai = use_ai and getattr(settings, "AI_IMPORT_ENABLED", False)
        ai_extensions = (".xlsx", ".xls", ".csv", ".tsv", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif")

        try:
            file_content = file_obj.read()

            if use_ai:
                if not str(file_obj.name or "").lower().endswith(ai_extensions):
                    return Response(
                        {"error": "Unsupported file type. Allowed: Excel, CSV, PDF, image, text."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                # MIME/magic byte validation (non-AI path is xlsx-only)
                if not _validate_xlsx_signature(file_content):
                    return Response(
                        {"error": "Invalid file format. Only .xlsx files are accepted."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            file_content_b64 = base64.b64encode(file_content).decode("ascii")
            task = process_excel_import.delay(
                deal_id, file_content_b64, request.user.id, use_ai=use_ai, filename=file_obj.name
            )

            # Store task ownership in DB (not volatile cache)
            ImportTask.objects.create(
                celery_task_id=task.id,
                owner=request.user,
                deal_id=deal_id,
                task_type="DEAL_IMPORT",
            )

            # Persist the ORIGINAL uploaded file as the deal's source-of-truth
            # attachment — both buyer and seller must always be able to download the
            # exact file the КП was parsed from. Shown in the deal's Documents panel.
            from django.core.files.base import ContentFile

            from .models import Attachment

            Attachment.objects.create(
                deal_id=deal_id,
                file=ContentFile(file_content, name=file_obj.name),
                original_filename=file_obj.name,
                uploaded_by=request.user,
            )

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
        except (OSError, ValueError, DatabaseError, OperationalError):
            # OSError/ValueError: file read/encode; DatabaseError: ImportTask/
            # Attachment create; OperationalError: Celery broker unreachable.
            logger.exception("Failed to queue Excel import task")
            return Response(
                {"error": "Failed to process import. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    summary="Import catalog from Excel",
    description=(
        "Upload an XLSX file to bulk-import products to the PIM catalog. "
        "Staff only. Max file size: 20MB. Returns a Celery task_id."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary", "description": "XLSX file"},
            },
        }
    },
    responses={
        202: OpenApiResponse(description="Import task queued"),
        400: OpenApiResponse(description="No file, invalid format, or too large"),
    },
    tags=["Sourcing"],
)
class CatalogImportView(APIView):
    """Bulk supplier catalog import.

    Accessible to (a) platform admin and (b) any authenticated user who is an
    active member of a SUPPLIER/MANUFACTURER company with `can_sell=True`.
    Task actor is captured in ImportTask.owner so admin can trace who uploaded
    what.
    """

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import_upload"

    def post(self, request):
        # Authorisation: allow platform admin OR a member with can_sell in
        # at least one SUPPLIER/MANUFACTURER company. The uploader's seller
        # company becomes the supplier on every upserted offer (self-service
        # path — supplier is NEVER a column in the file). Platform admin has no
        # company → products-only (no offers); the Unfold path is theirs.
        user = request.user
        is_admin = getattr(user, "is_platform_admin", False) or user.is_superuser
        supplier_company_id = None
        if not is_admin:
            from accounts.models import CompanyMember

            seller_membership = (
                CompanyMember.objects.filter(
                    user=user,
                    is_active=True,
                    can_sell=True,
                    company__types__code__in=["SUPPLIER", "MANUFACTURER"],
                )
                .order_by("-is_primary")
                .first()
            )
            if not seller_membership:
                return Response(
                    {"error": "NOT_A_SELLER_MEMBER"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            supplier_company_id = seller_membership.company_id

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"error": "No file uploaded"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"error": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            file_content = file_obj.read()

            if not _validate_xlsx_signature(file_content):
                return Response(
                    {"error": "Invalid file format. Only .xlsx files are accepted."}, status=status.HTTP_400_BAD_REQUEST
                )

            file_content_b64 = base64.b64encode(file_content).decode("ascii")
            # dry_run=true → validate + preview counts without persisting.
            dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
            task = process_catalog_import.delay(file_content_b64, supplier_company_id, dry_run)

            ImportTask.objects.create(
                celery_task_id=task.id,
                owner=request.user,
                task_type="CATALOG_IMPORT",
            )

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
        except (OSError, ValueError, DatabaseError, OperationalError):
            logger.exception("Failed to queue catalog import task")
            return Response(
                {"error": "Failed to process import. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    summary="Check import status",
    description=(
        "Check the status of a background import task by Celery task_id. "
        "Users can only check their own tasks; staff can check any task."
    ),
    responses={
        200: OpenApiResponse(description="Task status with result data if completed"),
        403: OpenApiResponse(description="No access to this task"),
    },
    tags=["Sourcing"],
)
class ImportStatusView(APIView):
    """Endpoint to check the status of a background import task."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        # IDOR protection: verify task ownership via DB (not cache)
        if not request.user.is_platform_admin:
            task_exists = ImportTask.objects.filter(celery_task_id=task_id, owner=request.user).exists()
            if not task_exists:
                return Response({"error": "You do not have access to this task"}, status=status.HTTP_403_FORBIDDEN)

        res = AsyncResult(task_id)
        result_data = None
        if res.ready():
            raw_result = res.result
            if isinstance(raw_result, dict):
                result_data = {
                    "status": raw_result.get("status"),
                    "items_processed": raw_result.get("items_processed"),
                    "message": (raw_result.get("message") if raw_result.get("status") == "error" else None),
                    # Structured catalog-import fields (None for deal imports).
                    "dry_run": raw_result.get("dry_run"),
                    "created": raw_result.get("created"),
                    "updated": raw_result.get("updated"),
                    "offers_upserted": raw_result.get("offers_upserted"),
                    "skipped": raw_result.get("skipped"),
                    "error_count": raw_result.get("error_count"),
                    "errors": raw_result.get("errors"),
                }
            else:
                result_data = {"status": "completed"}

        return Response({"task_id": task_id, "status": res.status, "result": result_data})


# Exact headers the import engine recognizes (see sourcing/catalog_import.py).
CATALOG_TEMPLATE_HEADERS = [
    "Наименование",
    "Бренд",
    "Артикул производителя",
    "ГОСТ / Чертёж",
    "Артикул поставщика",
    "Описание",
    "Ед. изм.",
    "Цена",
    "Валюта",
    "Наличие",
    "Срок поставки",
    "Мин. заказ",
]
CATALOG_TEMPLATE_EXAMPLE = [
    "Тормозная колодка",
    "Knorr-Bremse",
    "KB-100",
    "ГОСТ 1234-89",
    "SUP-55",
    "Композитная тормозная колодка",
    "шт",
    "150.50",
    "UZS",
    "IN_STOCK",
    "14-21 дн.",
    "5",
]


@extend_schema(
    summary="Download catalog import template",
    description=(
        "Returns an .xlsx with the exact headers the importer recognizes, one "
        "example row, and a reference sheet of allowed currency / stock / unit "
        "codes (read live from the database)."
    ),
    responses={200: OpenApiResponse(description="XLSX template")},
    tags=["Sourcing"],
)
class CatalogTemplateView(APIView):
    """Seller-facing catalog import template (true-PIM headers + allowed codes)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from openpyxl import Workbook

        from catalog.models import StockStatus
        from master_data.models import Currency, UnitOfMeasure

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Товары"
        sheet.append(CATALOG_TEMPLATE_HEADERS)
        sheet.append(CATALOG_TEMPLATE_EXAMPLE)

        reference = workbook.create_sheet("Справочники (коды)")
        reference.append(["Тип", "Код", "Название"])
        for currency in Currency.objects.all().order_by("code"):
            reference.append(["Валюта", currency.code, currency.name])
        for stock in StockStatus.objects.all().order_by("code"):
            reference.append(["Наличие", stock.code, stock.name])
        for unit in UnitOfMeasure.objects.all().order_by("code"):
            reference.append(["Ед. изм.", unit.code, unit.name])

        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="railtech_catalog_template.xlsx"'
        workbook.save(response)
        return response


@extend_schema_view(
    list=extend_schema(
        summary="List sourcing requests",
        description=("Returns deals in SOURCING stage. " "B2B filtered: users see only their company's deals."),
        tags=["Sourcing"],
    ),
    retrieve=extend_schema(
        summary="Get sourcing request details",
        description="Returns details of a specific sourcing request (deal in SOURCING stage).",
        tags=["Sourcing"],
    ),
)
class SourcingRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for retrieving sourcing requests (Deals in SOURCING stage).
    GET /api/v1/sourcing/requests/ - List all sourcing requests
    GET /api/v1/sourcing/requests/{id}/ - Get details of a specific request
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from crm.models import Deal

        if getattr(self, "swagger_fake_view", False):
            return Deal.objects.none()
        user = self.request.user
        queryset = (
            Deal.objects.filter(stage__code="SOURCING")
            .select_related("company", "client", "manager", "stage")
            .prefetch_related("quotes", "quotes__items")
        )

        # B2B Filter: User sees deals from their active companies
        if not (user.is_platform_admin):
            user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
            queryset = queryset.filter(company_id__in=user_company_ids)

        return queryset

    def get_serializer_class(self):
        # Use DealListSerializer for consistency with existing CRM endpoints
        from crm.serializers import DealListSerializer

        return DealListSerializer


class AttachmentViewSet(viewsets.ModelViewSet):
    """
    Uploads/lists/deletes private attachments tied to exactly one parent
    (deal, message, quote, company, or product).

    - list: filter by deal/message/quote/company/product query params.
    - create: requires ONE of deal/message/quote/company/product, plus `file`.
    - destroy: only uploader or platform admin.

    Access to the attached entity is checked via the deal's company membership
    (or the product's manufacturer, or the company directly).
    """

    from .models import Attachment as _AttachmentModel
    from .serializers import AttachmentSerializer

    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        # Stream the file through this authenticated endpoint (get_object enforces
        # tenant scope) — the raw .url 404s on prod (local storage, no MinIO).
        from core.file_streaming import stream_file_field

        return stream_file_field(self.get_object().file, content_type="application/octet-stream")

    def get_queryset(self):
        from crm.models import Deal

        from .models import Attachment

        if getattr(self, "swagger_fake_view", False):
            return Attachment.objects.none()
        user = self.request.user
        qs = Attachment.objects.select_related(
            "deal__company",
            "message__deal__company",
            "quote__deal__company",
            "company",
            "product__owner_company",
        ).order_by("-uploaded_at")

        params = self.request.query_params
        if params.get("deal"):
            qs = qs.filter(deal_id=params["deal"])
        if params.get("message"):
            qs = qs.filter(message_id=params["message"])
        if params.get("quote"):
            qs = qs.filter(quote_id=params["quote"])
        if params.get("company"):
            qs = qs.filter(company_id=params["company"])
        if params.get("product"):
            qs = qs.filter(product_id=params["product"])

        if user.is_platform_admin:
            return qs

        user_company_ids = user.memberships.filter(is_active=True).values("company_id")

        # Subquery: avoid loading all deal IDs into memory
        from django.db.models import Q

        accessible_deals = Deal.objects.filter(
            Q(company_id__in=user_company_ids) | Q(manager_id=user.id) | Q(client_id=user.id),
        ).values("id")

        return qs.filter(
            Q(deal_id__in=accessible_deals)
            | Q(message__deal_id__in=accessible_deals)
            | Q(quote__deal_id__in=accessible_deals)
            | Q(company_id__in=user_company_ids)
            | Q(product__owner_company_id__in=user_company_ids),
        )

    def _assert_parent_access(self, validated):
        """Before create, verify user can attach to the chosen parent."""
        from rest_framework.exceptions import PermissionDenied

        user = self.request.user
        if user.is_platform_admin:
            return

        user_company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))

        deal = validated.get("deal")
        message = validated.get("message")
        quote = validated.get("quote")
        company = validated.get("company")
        product = validated.get("product")

        target_deal = deal or (message.deal if message else None) or (quote.deal if quote else None)
        if target_deal:
            if (
                target_deal.company_id in user_company_ids
                or target_deal.manager_id == user.id
                or target_deal.client_id == user.id
            ):
                return
            raise PermissionDenied("NO_ACCESS_TO_DEAL")
        if company:
            if company.id in user_company_ids:
                return
            raise PermissionDenied("NO_ACCESS_TO_COMPANY")
        if product:
            if product.manufacturer_id and product.manufacturer_id in user_company_ids:
                return
            raise PermissionDenied("NO_ACCESS_TO_PRODUCT")
        raise PermissionDenied("NO_PARENT_PROVIDED")

    def perform_create(self, serializer):
        self._assert_parent_access(serializer.validated_data)
        file_obj = self.request.FILES.get("file")
        if not file_obj:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"file": "NO_FILE_PROVIDED"})
        serializer.save(
            uploaded_by=self.request.user,
            original_filename=file_obj.name,
        )

    def perform_destroy(self, instance):
        user = self.request.user
        if not (user.is_platform_admin or instance.uploaded_by_id == user.id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("ONLY_UPLOADER_OR_ADMIN_CAN_DELETE")
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()
