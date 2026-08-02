import base64
import logging

from celery.result import AsyncResult
from django.db import DatabaseError
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

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
                {"detail": "DEAL_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # IDOR protection: verify deal access
        if not _check_deal_access(request.user, deal):
            return Response({"detail": "DEAL_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "FILE_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # File size validation
        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"detail": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
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
                name_lower = str(file_obj.name or "").lower()
                if not name_lower.endswith(ai_extensions):
                    return Response(
                        {"detail": "UNSUPPORTED_FILE_TYPE"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # SEC-08: the extension is spoofable — verify the header matches it before we
                # base64 the bytes to Claude (text formats have no signature and pass; a .xlsx
                # that is really HTML/an executable is rejected).
                from core.validators import content_matches_extension

                ai_ext = "." + name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
                if not content_matches_extension(file_content[:16], ai_ext):
                    return Response(
                        {"detail": "FILE_CONTENT_MISMATCH"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                # MIME/magic byte validation (non-AI path is xlsx-only)
                if not _validate_xlsx_signature(file_content):
                    return Response(
                        {"detail": "XLSX_REQUIRED"},
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

            from .models import Attachment, AttachmentKind

            Attachment.objects.create(
                deal_id=deal_id,
                file=ContentFile(file_content, name=file_obj.name),
                original_filename=file_obj.name,
                uploaded_by=request.user,
                kind=AttachmentKind.SOURCE,
            )

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
        except (OSError, ValueError, DatabaseError, OperationalError):
            # OSError/ValueError: file read/encode; DatabaseError: ImportTask/
            # Attachment create; OperationalError: Celery broker unreachable.
            logger.exception("Failed to queue Excel import task")
            return Response(
                {"detail": "IMPORT_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    company__types__code="SUPPLIER",
                )
                .order_by("-is_primary")
                .first()
            )
            if not seller_membership:
                return Response(
                    {"detail": "NOT_A_SELLER_MEMBER"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            supplier_company_id = seller_membership.company_id

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "FILE_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"detail": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            file_content = file_obj.read()

            if not _validate_xlsx_signature(file_content):
                return Response(
                    {"detail": "XLSX_REQUIRED"},
                    status=status.HTTP_400_BAD_REQUEST,
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
                {"detail": "IMPORT_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                return Response({"detail": "TASK_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        res = AsyncResult(task_id)
        result_data = None
        if res.ready():
            raw_result = res.result
            if res.failed():
                # A hard crash (uncaught exception, time-limit, worker kill) leaves
                # res.result as an Exception instance — NOT a dict. Reporting that as
                # "completed" hides the failure from the UI, so surface a real "failed"
                # status with the error message instead.
                result_data = {
                    "status": "failed",
                    "message": str(raw_result) if raw_result else None,
                }
            elif isinstance(raw_result, dict):
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
