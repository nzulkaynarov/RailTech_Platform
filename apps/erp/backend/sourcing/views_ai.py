import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.permissions import BUYER_ONLY, RoleGatedViewMixin


@extend_schema(
    summary="AI semantic match: заявка lines → catalog products",
    description=(
        "For each request line (name / mpn / gost_drawing) returns up to top_k catalog "
        "Product candidates ranked by Claude (product_id always from a DB trigram shortlist — "
        "the model never invents ids). The buyer/seller confirms a candidate in the grid "
        "(human-in-loop). Capped at 50 lines per call. ARCH-01: the LLM call runs on Celery — "
        "returns 202 + task_id; poll sourcing/ai-status/<task_id>/ for {matches: []}."
    ),
    request=inline_serializer(
        "MatchCatalogRequest",
        fields={
            "lines": serializers.ListField(child=serializers.DictField()),
            "domain_code": serializers.CharField(required=False),
            "top_k": serializers.IntegerField(required=False),
        },
    ),
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned"),
        400: OpenApiResponse(description="Missing lines"),
        503: OpenApiResponse(description="AI matching disabled"),
    },
    tags=["Sourcing"],
)
class MatchCatalogView(RoleGatedViewMixin, APIView):
    """AI-assisted matching of free-text заявка lines to catalog.Product (roadmap #1)."""

    required_permissions = {
        "POST": "quote.build",
    }

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_match"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        lines = request.data.get("lines")
        if not isinstance(lines, list) or not lines:
            return Response({"detail": "LINES_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        domain_code = request.data.get("domain_code") or None
        try:
            top_k = max(1, min(5, int(request.data.get("top_k") or 3)))
        except (TypeError, ValueError):
            top_k = 3

        from .ai_jobs import enqueue_ai_job

        payload = {"lines": lines[:50], "domain_code": domain_code, "top_k": top_k}
        return enqueue_ai_job("match", payload, request.user)


@extend_schema(
    summary="AI pre-flight quality check for a заявка (advisory)",
    description=(
        "Runs an ADVISORY quality pass over draft request lines before the buyer "
        "submits the RFQ. Claude flags vague descriptions, missing/implausible qty or "
        "units, likely-duplicate lines and missing key specs. Returns warnings only — "
        "never a hard block (line_index always references a GIVEN line; out-of-range "
        "indices are dropped). Capped at 50 lines per call. ARCH-01: the LLM call runs on "
        "Celery — returns 202 + task_id; poll sourcing/ai-status/<task_id>/ for {findings: []}."
    ),
    request=inline_serializer(
        "PreflightCheckRequest",
        fields={
            "lines": serializers.ListField(child=serializers.DictField()),
            "domain_code": serializers.CharField(required=False),
        },
    ),
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned"),
        400: OpenApiResponse(description="Missing lines"),
        503: OpenApiResponse(description="AI pre-flight disabled"),
    },
    tags=["Sourcing"],
)
class PreflightCheckView(RoleGatedViewMixin, APIView):
    """AI advisory pre-submit quality check of buyer заявка lines (AI #7)."""

    required_permissions = {
        "POST": BUYER_ONLY,
    }
    buyer_actions = frozenset({"POST"})  # до M2-ERP-01

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_preflight"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        lines = request.data.get("lines")
        if not isinstance(lines, list) or not lines:
            return Response({"detail": "LINES_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        domain_code = request.data.get("domain_code") or None

        from .ai_jobs import enqueue_ai_job

        payload = {"lines": lines[:50], "domain_code": domain_code}
        return enqueue_ai_job("preflight", payload, request.user)


# Max size for an uploaded contract/invoice document (one base64 vision call). Aligned at
# request time to settings.AI_IMPORT_MAX_BYTES so the view's cap matches the service's (was
# 15MB vs 10MB → a 12MB file passed here then failed downstream as a confusing AI_EXTRACT_FAILED).
MAX_DOC_FILE_SIZE = 15 * 1024 * 1024
# Extensions file_to_payload can actually parse — anything else is rejected so an arbitrary
# binary can't be silently decoded as garbage text and still burn a paid extraction call.
_DOC_EXT_ALLOWLIST = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "csv", "txt", "tsv", "xlsx", "xls"}


def _resolve_expected(user, request, quote_id, contract_id):
    """Resolve the (expected_total, expected_currency_code, kind) record of truth for a
    Quote or Contract the user may see. Returns (None, None, None) when not found/visible.
    Scoping mirrors the billing viewset: platform admin sees all; everyone else only
    records on a deal owned by one of their active company memberships."""
    from crm.models import Contract, Quote

    is_admin = getattr(user, "is_superuser", False)
    company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))

    if contract_id:
        qs = Contract.objects.select_related("currency", "deal")
        contract = qs.filter(pk=contract_id).first()
        if contract is None:
            return None, None, None
        if not is_admin and contract.deal.company_id not in company_ids and contract.deal.client_id != user.id:
            return None, None, None
        currency_code = contract.currency.code if contract.currency_id else None
        return contract.total_amount, currency_code, "contract"

    qs = Quote.objects.select_related("quote_currency", "deal")
    quote = qs.filter(pk=quote_id).first()
    if quote is None:
        return None, None, None
    if not is_admin and quote.deal.company_id not in company_ids and quote.deal.client_id != user.id:
        return None, None, None
    currency_code = quote.quote_currency.code if quote.quote_currency_id else None
    return quote.total_incl_vat, currency_code, "quote"


@extend_schema(
    summary="AI extract + reconcile a signed contract / counter-invoice PDF (AI #6)",
    description=(
        "Buyer uploads a signed contract or counter-invoice (PDF/scan/image). Claude "
        "transcribes {total, currency_code, valid_until, bank_details, line_totals} with "
        "the same vision pattern as the заявка path; the financial comparison vs the "
        "referenced Quote/Contract is recomputed in CODE with Decimal precision (LLM "
        "numbers are never trusted for money). Flags total mismatch, foreign/unknown "
        "currency and expired date. Pass quote_id OR contract_id."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary", "description": "Contract/invoice PDF or image"},
                "quote_id": {"type": "integer"},
                "contract_id": {"type": "integer"},
            },
        }
    },
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned (poll sourcing/ai-status/<task_id>/)"),
        400: OpenApiResponse(description="No file or missing quote_id/contract_id"),
        404: OpenApiResponse(description="Quote/Contract not found or not visible"),
        503: OpenApiResponse(description="AI extraction disabled"),
    },
    tags=["Sourcing"],
)
class DocumentExtractView(RoleGatedViewMixin, APIView):
    """AI #6 — extract a contract/invoice PDF and reconcile it vs the КП/Contract in code."""

    required_permissions = {
        "POST": ("contract.manage", "quote.build"),
    }

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_extract"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"detail": "FILE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > getattr(settings, "AI_IMPORT_MAX_BYTES", MAX_DOC_FILE_SIZE):
            return Response({"detail": "FILE_TOO_LARGE"}, status=status.HTTP_400_BAD_REQUEST)
        extension = (uploaded.name or "").rsplit(".", 1)[-1].lower() if "." in (uploaded.name or "") else ""
        if extension not in _DOC_EXT_ALLOWLIST:
            return Response({"detail": "FILE_TYPE_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)
        # SEC-08: read the bytes once and verify the header matches the extension (spoof guard)
        # before handing them to the vision model; text formats have no signature and pass.
        from core.validators import content_matches_extension

        raw = uploaded.read()
        if not content_matches_extension(raw[:16], extension):
            return Response({"detail": "FILE_TYPE_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)

        def _to_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        quote_id = _to_int(request.data.get("quote_id"))
        contract_id = _to_int(request.data.get("contract_id"))
        if not quote_id and not contract_id:
            return Response({"detail": "QUOTE_OR_CONTRACT_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)

        expected_total, expected_currency, kind = _resolve_expected(request.user, request, quote_id, contract_id)
        if kind is None:
            return Response({"detail": "REFERENCE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        # ARCH-01: the visibility-scoped record of truth is resolved HERE (needs request.user);
        # the worker only receives the JSON-safe expected values + a STORAGE KEY for the
        # document. The bytes must never travel through the Redis broker: prod redis-celery
        # runs maxmemory 128mb + noeviction, so a handful of queued 10MB uploads would brick
        # every Celery publish platform-wide. The worker deletes the temp file after the run.
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from .ai_jobs import enqueue_ai_job

        file_key = default_storage.save(f"ai_extract_tmp/{uuid.uuid4().hex}.{extension}", ContentFile(raw))
        payload = {
            "file_key": file_key,
            "filename": uploaded.name,
            "expected_total": str(expected_total) if expected_total is not None else None,
            "expected_currency": expected_currency,
            "kind": kind,
            "reference_id": contract_id or quote_id,
        }
        return enqueue_ai_job("extract", payload, request.user)


@extend_schema(
    summary="Импорт позиций КП из файла продавцом (AI, Q2)",
    description=(
        "Продавец загружает файл (Excel/CSV/PDF/фото) в КОНКРЕТНЫЙ КП; Claude извлекает позиции "
        "(тем же vision-экстрактором, что заявку покупателя) и добавляет их В КОНЕЦ таблицы КП. "
        "ARCH-01: файл едет storage-ключом, извлечение — на Celery (202+task_id, поллинг "
        "sourcing/ai-status/). Тот же платформенный флаг AI_IMPORT_ENABLED, БЕЗ нового пейволла. "
        "Excel-вставка из буфера остаётся как быстрый путь."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "quote_id": {"type": "integer"},
            },
        }
    },
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned (poll ai-status)"),
        400: OpenApiResponse(description="No file / bad type / missing quote_id"),
        403: OpenApiResponse(description="Not own-company staff with pricing permission"),
        404: OpenApiResponse(description="Quote not found"),
        503: OpenApiResponse(description="AI import disabled"),
    },
    tags=["Sourcing"],
)
class QuoteImportFileView(RoleGatedViewMixin, APIView):
    """Q2 — seller-scoped file import of КП line items (mirrors DocumentExtractView staging)."""

    required_permissions = {
        "POST": "quote.build",
    }

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_extract"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            quote_id = int(request.data.get("quote_id"))
        except (TypeError, ValueError):
            return Response({"detail": "QUOTE_ID_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)

        # Seller-scoped authorization: only own-company staff with pricing capability may write
        # to THIS КП (mirrors the builder's bulk-create gate); the worker re-checks (TOCTOU) with
        # the recorded user.
        from accounts.services.permissions import can_edit_quote_pricing
        from crm.models import Quote

        quote = Quote.objects.select_related("deal").filter(pk=quote_id).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not (getattr(request.user, "is_superuser", False) or can_edit_quote_pricing(request.user)):
            return Response({"detail": "ONLY_SELLER_CAN_BUILD_QUOTE"}, status=status.HTTP_403_FORBIDDEN)
        if quote.frozen_at:
            return Response({"detail": "QUOTE_FROZEN"}, status=status.HTTP_400_BAD_REQUEST)

        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"detail": "FILE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > getattr(settings, "AI_IMPORT_MAX_BYTES", MAX_DOC_FILE_SIZE):
            return Response({"detail": "FILE_TOO_LARGE"}, status=status.HTTP_400_BAD_REQUEST)
        extension = (uploaded.name or "").rsplit(".", 1)[-1].lower() if "." in (uploaded.name or "") else ""
        if extension not in _DOC_EXT_ALLOWLIST:
            return Response({"detail": "FILE_TYPE_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)
        from core.validators import content_matches_extension

        raw = uploaded.read()
        if not content_matches_extension(raw[:16], extension):
            return Response({"detail": "FILE_TYPE_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from .ai_jobs import enqueue_ai_job

        file_key = default_storage.save(f"ai_extract_tmp/{uuid.uuid4().hex}.{extension}", ContentFile(raw))
        payload = {
            "file_key": file_key,
            "filename": uploaded.name,
            "quote_id": quote_id,
            "user_id": request.user.id,
        }
        return enqueue_ai_job("import_lines", payload, request.user)
