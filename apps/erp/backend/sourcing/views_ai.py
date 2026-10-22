import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin


@extend_schema(
    summary="AI semantic match: заявка lines → catalog products",
    description=(
        "For each request line (name / mpn / gost_drawing) returns up to top_k catalog "
        "Product candidates ranked by Claude (product_id always from a DB trigram shortlist — "
        "the model never invents ids). The client/seller confirms a candidate in the grid "
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

        from core.storage import get_temp_storage

        from .ai_jobs import enqueue_ai_job

        file_key = get_temp_storage().save(f"ai_extract_tmp/{uuid.uuid4().hex}.{extension}", ContentFile(raw))
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
        from crm.services.quotes.editable import quote_edit_lock_code

        lock_code = quote_edit_lock_code(quote)
        if lock_code:
            return Response({"detail": lock_code}, status=status.HTTP_409_CONFLICT)

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

        from core.storage import get_temp_storage

        from .ai_jobs import enqueue_ai_job

        file_key = get_temp_storage().save(f"ai_extract_tmp/{uuid.uuid4().hex}.{extension}", ContentFile(raw))
        payload = {
            "file_key": file_key,
            "filename": uploaded.name,
            "quote_id": quote_id,
            "user_id": request.user.id,
        }
        return enqueue_ai_job("import_lines", payload, request.user)


@extend_schema(
    summary="Разобрать текст заявки в строки КП (AI, FIX-67)",
    description=(
        "Заявка словами: клиент (или передача из CRM) описал потребность текстом, строк нет. Продавец жмёт "
        "«Разобрать текст в строки (ИИ)» в конструкторе КП — сервер берёт текст заявки сам (полный текст "
        "клиента, иначе комментарий сделки), разбирает его тем же извлечением, что и файл клиента "
        "(`ai.services.intake`), и дописывает строки В КОНЕЦ КП. ARCH-01: 202 + task_id, извлечение на Celery "
        "(поллинг sourcing/ai-status/). ИИ выключен — 503 `AI_DISABLED`, шлюз недоступен — результат задачи "
        "`AI_EXTRACT_FAILED`; ручной набор строк работает всегда. FIX-67b: пока разбор КП идёт, повторный запрос не "
        "ставит новую задачу (тот же сотрудник — 202 с прежним task_id и `already_running`; другой — 409 "
        "`PARSE_ALREADY_RUNNING`), запись строк идемпотентна по job."
    ),
    request=inline_serializer("ParseRequestTextRequest", fields={"quote_id": serializers.IntegerField()}),
    responses={
        202: OpenApiResponse(
            description=(
                "AI job queued, task_id returned (poll ai-status). `already_running: true` — разбор этого КП этим "
                "же сотрудником уже идёт: тот же task_id, новая задача не поставлена (FIX-67b)"
            )
        ),
        400: OpenApiResponse(description="QUOTE_ID_REQUIRED / REQUEST_TEXT_EMPTY"),
        403: OpenApiResponse(description="Not own-company staff with pricing permission"),
        404: OpenApiResponse(description="Quote not found"),
        409: OpenApiResponse(
            description=(
                "Quote is not editable (QUOTE_NOT_DRAFT / QUOTE_FROZEN) or a parse of this quote started by "
                "another user is still running (PARSE_ALREADY_RUNNING)"
            )
        ),
        503: OpenApiResponse(description="AI disabled (AI_DISABLED)"),
    },
    tags=["Sourcing"],
)
class QuoteParseRequestTextView(RoleGatedViewMixin, APIView):
    """FIX-67 — текст заявки → строки КП. Текст клиент не присылает: сервер читает его с самой сделки."""

    required_permissions = {
        "POST": "quote.build",
    }

    permission_classes = [IsAuthenticated]
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

        from accounts.services.permissions import can_edit_quote_pricing
        from crm.models import Quote
        from crm.services.draft_quote import deal_request_text
        from crm.services.quotes.editable import quote_edit_lock_code

        quote = Quote.objects.select_related("deal").filter(pk=quote_id).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not (getattr(request.user, "is_superuser", False) or can_edit_quote_pricing(request.user)):
            return Response({"detail": "ONLY_SELLER_CAN_BUILD_QUOTE"}, status=status.HTTP_403_FORBIDDEN)
        lock_code = quote_edit_lock_code(quote)
        if lock_code:
            return Response({"detail": lock_code}, status=status.HTTP_409_CONFLICT)
        if not deal_request_text(quote.deal):
            return Response({"detail": "REQUEST_TEXT_EMPTY"}, status=status.HTTP_400_BAD_REQUEST)

        from . import parse_text_guard
        from .ai_jobs import enqueue_ai_job

        # FIX-67b: in-flight-блокировка по КП. Занимаем ПОСЛЕ всех отказов (права/404/пустой текст), чтобы
        # отказанный запрос не оставлял «зависшую» блокировку.
        if not parse_text_guard.acquire(quote_id, request.user.id):
            held = parse_text_guard.holder(quote_id)
            acquired = False
            if held is not None and held[0] and parse_text_guard.job_is_finished(held[0]):
                # Задача упала молча (воркер убит): результат в backend есть, а блокировка не снята — не ждём TTL.
                # Снимаем лок ТОЛЬКО этого job: параллельный запрос мог уже занять новый (иначе два платных job).
                parse_text_guard.release(quote_id, held[0])
                acquired = parse_text_guard.acquire(quote_id, request.user.id)
                if not acquired:
                    held = parse_text_guard.holder(quote_id)
            if not acquired:
                task_id, owner_id = held or (None, None)
                if task_id and owner_id == request.user.id:
                    # Тот же сотрудник (двойной клик, вторая вкладка): тот же job, платная задача не ставится.
                    return Response({"task_id": task_id, "already_running": True}, status=status.HTTP_202_ACCEPTED)
                return Response({"detail": "PARSE_ALREADY_RUNNING"}, status=status.HTTP_409_CONFLICT)

        try:
            response = enqueue_ai_job(
                "parse_request_text", {"quote_id": quote_id, "user_id": request.user.id}, request.user
            )
        except Exception:
            parse_text_guard.release(quote_id)
            raise
        if response.status_code == status.HTTP_202_ACCEPTED:
            parse_text_guard.attach_task(quote_id, request.user.id, response.data["task_id"])
        else:
            parse_text_guard.release(quote_id)  # 429 (суточный лимит) / 500 (очередь): ничего не запущено
        return response
