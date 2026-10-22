import base64
import logging

from celery.result import AsyncResult
from django.db import DatabaseError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin

from .models import ImportTask
from .tasks import process_catalog_import, process_excel_import

# Шаблон импорта вынесен в views_templates.py (файл перерос предел 500 строк, R5b);
# ре-экспорт сохраняет прежние точки импорта (тесты, фасад sourcing/views.py).
from .views_templates import CATALOG_TEMPLATE_EXAMPLE, CATALOG_TEMPLATE_HEADERS, CatalogTemplateView  # noqa: F401

logger = logging.getLogger(__name__)

# Max Excel file size: 20MB
MAX_EXCEL_FILE_SIZE = 20 * 1024 * 1024

# XLSX magic bytes (ZIP/PK header)
XLSX_MAGIC = b"PK\x03\x04"


def _validate_xlsx_signature(file_bytes: bytes) -> bool:
    """Validate that file starts with ZIP/XLSX magic bytes."""
    return file_bytes[:4] == XLSX_MAGIC


def _resolve_seller_company(user):
    """Продавцовая авторизация каталожного импорта → (supplier_company_id, error_response).

    Platform admin → (None, None): продукты без офферов (компании у него нет). Иначе нужен
    активный член SUPPLIER-компании с can_sell — его компания и станет supplier на офферах
    (self-service: supplier НИКОГДА не колонка файла). Не продавец → (None, 403).
    """
    if getattr(user, "is_superuser", False) or user.is_superuser:
        return None, None
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
        return None, Response({"detail": "NOT_A_SELLER_MEMBER"}, status=status.HTTP_403_FORBIDDEN)
    return seller_membership.company_id, None


def _check_deal_access(user, deal) -> bool:
    """Centralized deal access check to prevent IDOR."""
    if user.is_superuser:
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
        409: OpenApiResponse(description="QUOTE_NOT_DRAFT / QUOTE_FROZEN: активное КП сделки уже не черновик"),
    },
    tags=["Sourcing"],
)
class ExcelImportView(RoleGatedViewMixin, APIView):
    """Endpoint for deal-specific excel imports.
    Both clients (for own deals) and managers can import.
    Deal access is verified inside the view via _check_deal_access.
    """

    required_permissions = {
        "POST": "deal.manage",
    }

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

        # Импорт дописывает строки в активное КП сделки — только пока оно в черновике (FIX-55, D-04).
        from crm.services.quotes.editable import quote_edit_lock_code

        active_quote = deal.active_quote
        lock_code = quote_edit_lock_code(active_quote) if active_quote is not None else None
        if lock_code:
            return Response({"detail": lock_code}, status=status.HTTP_409_CONFLICT)

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
            return Response({"detail": "IMPORT_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
class CatalogImportView(RoleGatedViewMixin, APIView):
    """Bulk supplier catalog import.

    Accessible to (a) platform admin and (b) any authenticated user who is an
    active member of a SUPPLIER/MANUFACTURER company with `can_sell=True`.
    Task actor is captured in ImportTask.owner so admin can trace who uploaded
    what.
    """

    required_permissions = {
        "POST": "catalog.manage",
    }

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import_upload"

    def post(self, request):
        # Authorisation: platform admin (products-only, no offers — has no company; the
        # Unfold path is theirs) OR a can_sell member of a SUPPLIER company, whose company
        # becomes the supplier on every upserted offer (see _resolve_seller_company).
        supplier_company_id, auth_error = _resolve_seller_company(request.user)
        if auth_error is not None:
            return auth_error

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
            return Response({"detail": "IMPORT_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Файлы, из которых ИИ-путь умеет доставать прайс: наш xlsx (бесплатный разбор без токенов
# внутри extract_price_rows) + PDF/фото — vision-механизм заявок (services_ai_catalog).
AI_CATALOG_EXTENSIONS = ("xlsx", "pdf", "png", "jpg", "jpeg")


@extend_schema(
    summary="Импорт каталога ЛЮБЫМ файлом через ИИ (R5b)",
    description=(
        "Продавец загружает прайс-лист как есть — xlsx/PDF/фото. Наш xlsx-шаблон разбирается "
        "бесплатно (без вызова ИИ); остальное дословно переносит Claude в схему шаблона, после "
        "чего строки идут через штатный движок импорта (тот же отчёт created/updated/errors). "
        "ARCH-01: файл едет storage-ключом, извлечение — на Celery. Возвращает 202 {task_id}; "
        "поллинг sourcing/ai-status/<task_id>/ — результат = отчёт импорта + ai_used/ai_rows. "
        "dry_run=true — предпросмотр без записи."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary", "description": "Прайс-лист: xlsx/pdf/png/jpg"},
                "dry_run": {"type": "boolean"},
            },
        }
    },
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned (poll sourcing/ai-status/)"),
        400: OpenApiResponse(description="No file, unsupported type, spoofed content or too large"),
        403: OpenApiResponse(description="Not a can_sell member of a SUPPLIER company"),
        503: OpenApiResponse(description="AI import disabled"),
    },
    tags=["Sourcing"],
)
class ImportCatalogAiView(RoleGatedViewMixin, APIView):
    """R5b — зеркало CatalogImportView для произвольных файлов (staging как у extract-document).

    Дневной предохранитель расхода ИИ применяется внутри enqueue_ai_job.
    """

    required_permissions = {
        "POST": "catalog.manage",
    }

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import_upload"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        supplier_company_id, auth_error = _resolve_seller_company(request.user)
        if auth_error is not None:
            return auth_error

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "FILE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response({"detail": "FILE_TOO_LARGE"}, status=status.HTTP_400_BAD_REQUEST)
        name_lower = str(file_obj.name or "").lower()
        extension = name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
        if extension not in AI_CATALOG_EXTENSIONS:
            return Response({"detail": "FILE_TYPE_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)

        # SEC-08: расширение подделываемо — сверяем магию заголовка с ним до staging/оплаты
        # (тот же байтовый гард, что у AI-путей extract-document / import-quote-lines).
        from core.validators import content_matches_extension

        raw = file_obj.read()
        if not content_matches_extension(raw[:16], extension):
            return Response({"detail": "FILE_CONTENT_MISMATCH"}, status=status.HTTP_400_BAD_REQUEST)

        # ARCH-01: байты НИКОГДА не едут через Redis-брокер — staging в бакете erp-temp (файловая система у backend и воркера разная),
        # воркер читает по ключу и удаляет файл после попытки (см. _handle_catalog_import_ai).
        import uuid

        from django.core.files.base import ContentFile

        from core.storage import get_temp_storage

        from .ai_jobs import enqueue_ai_job

        storage_path = get_temp_storage().save(f"ai_extract_tmp/{uuid.uuid4().hex}.{extension}", ContentFile(raw))
        payload = {
            "storage_path": storage_path,
            "filename": file_obj.name,
            "supplier_company_id": supplier_company_id,
            "dry_run": str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes"),
        }
        return enqueue_ai_job("catalog_import_ai", payload, request.user)


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
        if not request.user.is_superuser:
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
                    # Мягкие замечания и цена наполнения: без них отчёт бодро рапортует
                    # «создано 3000», умалчивая, что опубликовать нельзя ни одну карточку.
                    "warning_count": raw_result.get("warning_count"),
                    "warnings": raw_result.get("warnings"),
                    "unpublishable": raw_result.get("unpublishable"),
                    "missing_breakdown": raw_result.get("missing_breakdown"),
                    "rows_truncated": raw_result.get("rows_truncated"),
                }
            else:
                result_data = {"status": "completed"}

        return Response({"task_id": task_id, "status": res.status, "result": result_data})
