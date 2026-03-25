import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from celery.result import AsyncResult

from core.permissions import IsManagerOrAdmin
from .models import ImportTask
from .tasks import process_excel_import, process_catalog_import

logger = logging.getLogger(__name__)

# Max Excel file size: 20MB
MAX_EXCEL_FILE_SIZE = 20 * 1024 * 1024

# XLSX magic bytes (ZIP/PK header)
XLSX_MAGIC = b'PK\x03\x04'


def _validate_xlsx_signature(file_bytes: bytes) -> bool:
    """Validate that file starts with ZIP/XLSX magic bytes."""
    return file_bytes[:4] == XLSX_MAGIC


def _check_deal_access(user, deal) -> bool:
    """Centralized deal access check to prevent IDOR."""
    if user.is_superuser:
        return True
    if hasattr(user, 'role') and user.role and user.role.is_staff_level:
        return True
    if deal.manager_id == user.id:
        return True
    if deal.company:
        return user.memberships.filter(
            company=deal.company, is_active=True
        ).exists()
    return deal.client_id == user.id


class ExcelImportView(APIView):
    """Endpoint for deal-specific excel imports.
    Both clients (for own deals) and managers can import.
    Deal access is verified inside the view via _check_deal_access.
    """
    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]

    def post(self, request, deal_id):
        from crm.models import Deal
        try:
            deal = Deal.objects.select_related('company').get(pk=deal_id)
        except Deal.DoesNotExist:
            return Response({"error": "Deal not found"}, status=status.HTTP_404_NOT_FOUND)

        # IDOR protection: verify deal access
        if not _check_deal_access(request.user, deal):
            return Response(
                {"error": "You do not have access to this deal"},
                status=status.HTTP_403_FORBIDDEN
            )

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        # File size validation
        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"error": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            file_content = file_obj.read()

            # MIME/magic byte validation
            if not _validate_xlsx_signature(file_content):
                return Response(
                    {"error": "Invalid file format. Only .xlsx files are accepted."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            task = process_excel_import.delay(deal_id, file_content, request.user.id)

            # Store task ownership in DB (not volatile cache)
            ImportTask.objects.create(
                celery_task_id=task.id,
                owner=request.user,
                deal_id=deal_id,
                task_type='DEAL_IMPORT',
            )

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
        except Exception:
            logger.exception("Failed to queue Excel import task")
            return Response(
                {"error": "Failed to process import. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CatalogImportView(APIView):
    """Endpoint for bulk supplier catalog imports (staff only)."""
    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        if file_obj.size > MAX_EXCEL_FILE_SIZE:
            return Response(
                {"error": f"File too large (max {MAX_EXCEL_FILE_SIZE // (1024*1024)}MB)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            file_content = file_obj.read()

            if not _validate_xlsx_signature(file_content):
                return Response(
                    {"error": "Invalid file format. Only .xlsx files are accepted."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            task = process_catalog_import.delay(file_content)

            ImportTask.objects.create(
                celery_task_id=task.id,
                owner=request.user,
                task_type='CATALOG_IMPORT',
            )

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
        except Exception:
            logger.exception("Failed to queue catalog import task")
            return Response(
                {"error": "Failed to process import. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ImportStatusView(APIView):
    """Endpoint to check the status of a background import task."""
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        # IDOR protection: verify task ownership via DB (not cache)
        is_staff = request.user.is_superuser or (
            hasattr(request.user, 'role') and request.user.role
            and request.user.role.is_staff_level
        )

        if not is_staff:
            task_exists = ImportTask.objects.filter(
                celery_task_id=task_id, owner=request.user
            ).exists()
            if not task_exists:
                return Response(
                    {"error": "You do not have access to this task"},
                    status=status.HTTP_403_FORBIDDEN
                )

        res = AsyncResult(task_id)
        result_data = None
        if res.ready():
            raw_result = res.result
            if isinstance(raw_result, dict):
                result_data = {
                    'status': raw_result.get('status'),
                    'items_processed': raw_result.get('items_processed'),
                    'message': raw_result.get('message') if raw_result.get('status') == 'error' else None,
                }
            else:
                result_data = {'status': 'completed'}

        return Response({
            "task_id": task_id,
            "status": res.status,
            "result": result_data
        })


class SourcingRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for retrieving sourcing requests (Deals in SOURCING stage).
    GET /api/v1/sourcing/requests/ - List all sourcing requests
    GET /api/v1/sourcing/requests/{id}/ - Get details of a specific request
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from crm.models import Deal

        user = self.request.user
        queryset = Deal.objects.filter(
            stage__code='SOURCING'
        ).select_related('company', 'client', 'manager', 'stage').prefetch_related(
            'quotes', 'quotes__items'
        )

        # B2B Filter: User sees deals from their active companies
        if not (user.is_superuser or user.is_manager_or_admin):
            user_company_ids = user.memberships.filter(
                is_active=True
            ).values_list('company_id', flat=True)
            queryset = queryset.filter(company_id__in=user_company_ids)

        return queryset

    def get_serializer_class(self):
        # Use DealListSerializer for consistency with existing CRM endpoints
        from crm.serializers import DealListSerializer
        return DealListSerializer
