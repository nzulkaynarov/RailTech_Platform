"""ARCH-01 — off-thread runner for the interactive AI endpoints.

Each of the 8 request-path LLM endpoints used to call Claude synchronously inside a DRF
view, pinning an ASGI threadpool thread for up to AI_REQUEST_TIMEOUT seconds. They now
enqueue ONE generic Celery task (queue "ai") and return 202 + task_id; the frontend polls
GET sourcing/ai-status/<task_id>/ (see `sourcing.ai_jobs`), mirroring the proven Excel
import pattern.

Every handler takes a JSON-safe payload dict (the view resolves and serializes anything
that needs the request/user visibility scope BEFORE enqueue) and returns the EXACT same
JSON-shaped dict the old synchronous view returned, so the frontend result contract is
unchanged. Business-gate failures are returned as {"error": CODE} results — never raised.
The task runs a SINGLE attempt (no autoretry — see run_ai_job) because every handler is a
paid-per-call LLM request and draft_quote also commits writes + billing.
"""

import logging
from types import SimpleNamespace

from celery import shared_task

logger = logging.getLogger(__name__)


def _handle_match(payload: dict) -> dict:
    from sourcing.services_ai import match_lines_to_catalog

    matches = match_lines_to_catalog(
        payload["lines"],
        domain_code=payload.get("domain_code"),
        top_k=payload.get("top_k") or 3,
    )
    return {"matches": matches}


def _handle_preflight(payload: dict) -> dict:
    from sourcing.services_ai_preflight import pre_flight_check

    findings = pre_flight_check(payload["lines"], domain_code=payload.get("domain_code"))
    return {"findings": findings}


def _handle_extract(payload: dict) -> dict:
    """AI #6 — vision-extract a contract/invoice, then reconcile vs the КП/Contract in code.

    The view resolves the (expected_total, expected_currency, kind) record of truth with
    its visibility checks BEFORE enqueue and ships them JSON-safe (total as str) — the
    worker never re-does request-scoped authorization. The document itself travels as a
    default_storage key (NOT base64 through the broker: prod redis-celery runs maxmemory
    128mb + noeviction, so a handful of queued 10MB uploads would brick all of Celery);
    the temp file is always deleted after the attempt.
    """
    from django.core.files.storage import default_storage

    from sourcing.services_ai_extract import extract_document_fields, reconcile

    file_key = payload["file_key"]
    try:
        with default_storage.open(file_key) as stored:
            raw = stored.read()
        try:
            extracted = extract_document_fields(raw, payload["filename"])
        except RuntimeError as exc:
            # Same contract as the old sync view's 503: a stable error code the frontend maps.
            logger.warning("AI doc-extract failed: %s", exc)
            return {"error": "AI_EXTRACT_FAILED"}
    finally:
        default_storage.delete(file_key)

    comparison = reconcile(extracted, payload.get("expected_total"), payload.get("expected_currency"))
    return {
        "reference": {"kind": payload.get("kind"), "id": payload.get("reference_id")},
        "extracted": extracted,
        "comparison": comparison,
    }


def _handle_import_lines(payload: dict) -> dict:
    """Q2 — импорт позиций КП из файла продавцом: vision-извлечение строк (Excel/PDF/фото) →
    вставка в КП продавца. Тот же экстрактор, что у покупателя (extract_request_items), но цель —
    КОНКРЕТНЫЙ КП по quote_id, а не deal.active_quote. Авторизация перепроверяется с записанным
    user (TOCTOU — как quote_diff): под очередью routing мог быть отозван. Файл едет storage-ключом
    (не через брокер), удаляется после попытки."""
    from django.core.files.storage import default_storage

    from accounts.models import CustomUser
    from crm.models import Quote
    from crm.services.quotes.bulk import import_extracted_lines_into_quote
    from sourcing.services_ai import extract_request_items

    file_key = payload["file_key"]
    user = CustomUser.objects.filter(pk=payload["user_id"]).first()
    quote = Quote.objects.select_related("deal", "cost_currency_default").filter(pk=payload["quote_id"]).first()
    if user is None or quote is None:
        default_storage.delete(file_key)
        return {"error": "QUOTE_NOT_FOUND"}
    try:
        with default_storage.open(file_key) as stored:
            raw = stored.read()
        try:
            rows = extract_request_items(raw, payload.get("filename") or "upload")
        except (RuntimeError, ValueError) as exc:
            logger.warning("AI import-lines extract failed: %s", exc)
            return {"error": "AI_EXTRACT_FAILED"}
    finally:
        default_storage.delete(file_key)

    added, truncated, err = import_extracted_lines_into_quote(quote, user, rows)
    if err:
        return {"error": err}
    return {"added": added, "recognized": len(rows), "truncated": truncated, "quote_id": quote.id}


def _handle_compose(payload: dict) -> dict:
    from sourcing.services_ai_conversational import build_request_from_text

    return build_request_from_text(payload["text"], domain_code=payload.get("domain_code"))


def _handle_enrich(payload: dict) -> dict:
    from catalog.ai_enrich import enrich_product

    suggestion = enrich_product(
        payload["name"],
        domain_code=payload.get("domain_code"),
        mpn=payload.get("mpn"),
        gost=payload.get("gost"),
    )
    return {"suggestion": suggestion}


def _handle_chat_reply(payload: dict) -> dict:
    from accounts.models import CustomUser
    from crm.services import suggest_chat_reply

    user = CustomUser.objects.get(pk=payload["user_id"])
    return suggest_chat_reply(payload["deal_id"], user)


def _handle_quote_diff(payload: dict) -> dict:
    from accounts.models import CustomUser
    from crm.models import Quote
    from crm.services import quote_vs_request_diff, user_can_view_quote_diff

    quote = Quote.objects.select_related("deal").get(pk=payload["quote_id"])
    # Re-run the visibility gate with the recorded user: the view checked it at enqueue,
    # but under queue latency a routing revocation / member deactivation must not still
    # deliver the diff minutes later (TOCTOU — mirrors chat_reply re-running its scoping).
    user = CustomUser.objects.get(pk=payload["user_id"])
    if not user_can_view_quote_diff(user, quote):
        return {"error": "NOT_AUTHORIZED"}
    return quote_vs_request_diff(quote)


def _handle_draft_quote(payload: dict) -> dict:
    """ADR-0006 Move 3 — build the pre-filled draft КП off-thread.

    The service's gate errors (stable UPPER_SNAKE codes) are mapped into an {"error": CODE}
    result — the frontend helper raises them as Error(CODE) for the existing apiErrors.* map.
    The success shape mirrors the old sync view exactly: {prefilled, quote_id, deal}.
    """
    from accounts.models import CustomUser
    from crm.models import Deal
    from crm.serializers import DealDetailSerializer
    from crm.services.draft_quote import generate_draft_quote

    user = CustomUser.objects.get(pk=payload["user_id"])
    quote, err, prefilled = generate_draft_quote(payload["deal_id"], user)
    if err:
        return {"error": err}
    deal = Deal.objects.get(pk=quote.deal_id)
    # The serializer's viewer-scoped fields (cost redaction, assigned_to, can_edit_request)
    # only read `request.user` — a user-carrying stand-in preserves the actor's projection
    # exactly as the old synchronous response did (the result is only readable by the owner).
    # build_absolute_uri is required by nested raw FileFields (Quote.pdf_file): returning
    # the URL unchanged yields a RELATIVE url, which is acceptable — the SPA downloads PDFs
    # via the authenticated download-pdf endpoint and never dereferences this field directly.
    serializer_context = {"request": SimpleNamespace(user=user, build_absolute_uri=lambda url: url)}
    return {
        "prefilled": prefilled,
        "quote_id": quote.id,
        "deal": DealDetailSerializer(deal, context=serializer_context).data,
    }


def _handle_suggest_sellers(payload: dict) -> dict:
    """R3 — AI-enhanced seller-routing suggestions off-thread. The view already buyer-gated the
    deal before enqueue; the worker just runs the enhanced (trigram + AI fallback) match. Falls
    back to the deterministic result inside the service when AI is off / finds nothing."""
    from crm.models import Deal
    from sourcing.services import suggest_sellers_for_deal_ai

    deal = Deal.objects.filter(pk=payload["deal_id"]).first()
    if deal is None:
        return {"error": "DEAL_NOT_FOUND"}
    return {"sellers": suggest_sellers_for_deal_ai(deal)}


def _handle_hs_lookup(payload: dict, user_id: int) -> dict:
    """T3: «опишите товар своими словами» → код ТН ВЭД из справочника с объяснением."""
    from catalog.hs_lookup_ai import lookup_hs_code

    return lookup_hs_code(payload.get("description") or "")


FEATURE_HANDLERS = {
    "match": _handle_match,
    "preflight": _handle_preflight,
    "extract": _handle_extract,
    "import_lines": _handle_import_lines,
    "compose": _handle_compose,
    "enrich": _handle_enrich,
    "chat_reply": _handle_chat_reply,
    "quote_diff": _handle_quote_diff,
    "draft_quote": _handle_draft_quote,
    "suggest_sellers": _handle_suggest_sellers,
    "hs_lookup": _handle_hs_lookup,
}


# SINGLE ATTEMPT — deliberate deviation from the CLAUDE.md Celery convention
# (max_retries=3, autoretry_for=(Exception,), retry_backoff=True): every feature here is
# a paid-per-call Claude request (compose fires TWO calls per attempt), and draft_quote
# commits writes + consumes an AI_DRAFT credit inside the handler. A blanket autoretry
# would multiply the spend up to 4x and, on any post-commit failure, duplicate the created
# quote and the billed credit. An interactive failure must surface to the user (who simply
# clicks again) — never silently re-execute.
@shared_task(
    bind=True,
    name="sourcing.run_ai_job",
    queue="ai",
    time_limit=600,
    soft_time_limit=540,
    max_retries=0,
)
def run_ai_job(self, feature: str, payload: dict) -> dict:
    """Dispatch one off-thread AI job to its feature handler (ARCH-01, single attempt)."""
    handler = FEATURE_HANDLERS.get(feature)
    if handler is None:
        raise ValueError(f"Unknown AI job feature: {feature}")
    return handler(payload)
