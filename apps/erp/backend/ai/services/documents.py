"""Денежные поля договора / встречного счёта + сверка в коде (feature `extract`, `intake-model`).

On the contract→invoice steps a buyer uploads a signed contract or a counter-invoice
PDF (or scan/image). The model reads the document with the SAME vision pattern proven in
the заявка path (`payloads.file_to_payload`) and
returns a STRUCTURED snapshot of the money-bearing fields: total, currency, valid-until,
bank details and per-line totals.

IRON RULE — money is reconciled in CODE, never trusted from the LLM. The model only
TRANSCRIBES what it sees on the page; every comparison against the Quote/Contract row
of record (total mismatch, foreign currency, expired date) is recomputed here with
`decimal.Decimal` precision. The LLM output is treated as untrusted OCR.

Currency codes are validated against `master_data.Currency` (source of truth) — an
ISO code the model reads that is not in our справочник is surfaced as UNKNOWN, never
silently accepted.

Gated behind `settings.AI_IMPORT_ENABLED`: `extract_document_fields` raises
`RuntimeError("AI_IMPORT_DISABLED")` when off so the caller can degrade. The pure
reconciliation helper (`reconcile`) has NO I/O and is unit-tested directly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from .gateway import JsonCall, call_json, text_block
from .payloads import file_to_payload
from .prompts import load_prompt

logger = logging.getLogger(__name__)

# Structured Outputs schema — the model TRANSCRIBES the document. All props required
# (additionalProperties=false forbids optional). Numbers come back as strings so we
# never lose Decimal precision to a JSON float (Rule: money is parsed in code).
LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "Наименование позиции как в документе"},
        "line_total": {
            "type": "string",
            "description": "Сумма по строке (итог за позицию) СТРОКОЙ как в документе, напр. '1234567.89'. '' если нет.",
        },
    },
    "required": ["description", "line_total"],
    "additionalProperties": False,
}
DOC_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "total": {
            "type": "string",
            "description": "Итоговая сумма документа (Grand Total, с НДС) СТРОКОЙ, напр. '1234567.89'. '' если не найдена.",
        },
        "currency_code": {
            "type": "string",
            "description": "Код валюты ISO 4217 (UZS, USD, EUR, RUB …). '' если не указана/непонятна.",
        },
        "valid_until": {
            "type": "string",
            "description": "Срок действия / дата оплаты до в формате YYYY-MM-DD. '' если нет.",
        },
        "bank_details": {
            "type": "string",
            "description": "Банковские реквизиты получателя (банк, р/с, МФО/SWIFT, ИНН) одной строкой. '' если нет.",
        },
        "line_totals": {"type": "array", "items": LINE_SCHEMA},
    },
    "required": ["total", "currency_code", "valid_until", "bank_details", "line_totals"],
    "additionalProperties": False,
}

# Cap so one base64 vision call stays bounded (mirrors services_ai default).
MAX_LINE_TOTALS = 200


def _parse_money(raw) -> Decimal | None:
    """Parse the model's money string to a Decimal. Tolerates spaces, NBSP, a comma
    decimal separator and stray currency glyphs. Returns None when not a number — the
    caller treats that as 'document did not state it' (never a silent 0)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Strip everything except digits, separators and sign; normalise comma → dot.
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".,-")
    cleaned = cleaned.replace(",", ".")
    # Collapse multiple dots (thousands written as 1.234.567) — keep only the last as decimal.
    if cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _parse_iso_date(raw) -> date | None:
    """Parse a YYYY-MM-DD string from the model. None when absent/unparseable."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


EMPTY_FIELDS = {"total": "", "currency_code": "", "valid_until": "", "bank_details": "", "line_totals": []}


def _document_content(content: bytes, filename: str) -> list[dict]:
    text, vision_block = file_to_payload(content, filename)
    if vision_block is not None:
        return [vision_block, text_block("Извлеки финансовые поля из этого документа.")]
    # Non-vision upload (csv/txt) — feed the decoded text. Bounded by the byte cap.
    return [text_block(f"Текст документа:\n\n{text}")]


def _clean_fields(data: dict) -> dict:
    line_totals = [
        {
            "description": str(line.get("description") or "").strip()[:500],
            "line_total": str(line.get("line_total") or "").strip()[:32],
        }
        for line in (data.get("line_totals") or [])[:MAX_LINE_TOTALS]
        if isinstance(line, dict)
    ]
    return {
        "total": str(data.get("total") or "").strip()[:32],
        "currency_code": str(data.get("currency_code") or "").strip().upper()[:8],
        "valid_until": str(data.get("valid_until") or "").strip()[:10],
        "bank_details": str(data.get("bank_details") or "").strip()[:1000],
        "line_totals": line_totals,
    }


def extract_document_fields(content: bytes, filename: str) -> dict:
    """Uploaded bytes (PDF / image / scan) → transcribed financial fields.

    Returns {total, currency_code, valid_until, bank_details, line_totals:[{description,
    line_total}]} — strings exactly as the model read them (money/dates parsed downstream
    by `reconcile`, which is the trusted side). Raises RuntimeError("AI_IMPORT_DISABLED")
    when AI is off, RuntimeError("AI_IMPORT_FILE_TOO_LARGE") over the byte cap and
    RuntimeError("AI_GATEWAY_UNAVAILABLE") when the gateway gave no answer. Returns
    empty/neutral fields on a refusal or unparseable response."""
    if not getattr(settings, "AI_IMPORT_ENABLED", False):
        raise RuntimeError("AI_IMPORT_DISABLED")
    max_bytes = getattr(settings, "AI_IMPORT_MAX_BYTES", 10 * 1024 * 1024)
    if len(content) > max_bytes:
        raise RuntimeError(f"AI_IMPORT_FILE_TOO_LARGE ({len(content)} > {max_bytes} bytes)")

    prompt = load_prompt("extract")
    result = call_json(
        JsonCall(
            feature="extract",
            prompt=prompt,
            system=prompt.render(),
            user_content=_document_content(content, filename),
            schema=DOC_RESULT_SCHEMA,
            max_tokens=4000,
            mask_input=True,
        )
    )
    if result.status in ("error", "disabled"):
        raise RuntimeError(result.error_code or "AI_GATEWAY_UNAVAILABLE")
    if not result.ok:
        return dict(EMPTY_FIELDS, line_totals=[])
    return _clean_fields(result.data)


def _valid_currency_codes() -> set[str]:
    """Active ISO currency codes from the справочник (source of truth — Rule 1)."""
    from master_data.models import Currency

    return {code.upper() for code in Currency.objects.filter(is_active=True).values_list("code", flat=True)}


def reconcile(extracted: dict, expected_total, expected_currency_code: str | None, tolerance: str = "0.01") -> dict:
    """Compare extracted (untrusted) fields against the DB record of truth in CODE.

    PURE function — no I/O, unit-tested directly. `expected_total` is the Quote/Contract
    total (Decimal/str/number); `expected_currency_code` the document's currency code.
    Money is compared with Decimal at `tolerance` (default 1 tiyin) — LLM numbers are
    NEVER trusted for the verdict, only re-parsed and re-compared here.

    Returns {ok: bool, mismatches: [{code, ...}], parsed: {...}} where each mismatch
    `code` is a stable machine code (compared by code, not translated name):
      TOTAL_MISMATCH, CURRENCY_UNKNOWN, FOREIGN_CURRENCY, DOCUMENT_EXPIRED,
      TOTAL_NOT_FOUND, CURRENCY_NOT_FOUND.
    """
    mismatches: list[dict] = []

    doc_total = _parse_money(extracted.get("total"))
    try:
        expected = Decimal(str(expected_total)) if expected_total is not None else None
    except (InvalidOperation, ValueError):
        expected = None
    tol = Decimal(tolerance)

    if doc_total is None:
        mismatches.append({"code": "TOTAL_NOT_FOUND"})
    elif expected is not None and (doc_total - expected).copy_abs() > tol:
        # Total on the page ≠ КП/Contract total — the headline reconciliation flag.
        mismatches.append(
            {
                "code": "TOTAL_MISMATCH",
                "document_total": str(doc_total),
                "expected_total": str(expected),
                "difference": str(doc_total - expected),
            }
        )

    doc_currency = (extracted.get("currency_code") or "").strip().upper()
    if not doc_currency:
        mismatches.append({"code": "CURRENCY_NOT_FOUND"})
    else:
        valid_codes = _valid_currency_codes()
        if doc_currency not in valid_codes:
            mismatches.append({"code": "CURRENCY_UNKNOWN", "document_currency": doc_currency})
        elif expected_currency_code and doc_currency != (expected_currency_code or "").strip().upper():
            # Document is in a different currency than the КП/Contract — FX risk flag.
            mismatches.append(
                {
                    "code": "FOREIGN_CURRENCY",
                    "document_currency": doc_currency,
                    "expected_currency": (expected_currency_code or "").strip().upper(),
                }
            )

    valid_until = _parse_iso_date(extracted.get("valid_until"))
    if valid_until is not None and valid_until < timezone.localdate():
        mismatches.append({"code": "DOCUMENT_EXPIRED", "valid_until": valid_until.isoformat()})

    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "parsed": {
            "document_total": str(doc_total) if doc_total is not None else None,
            "document_currency": doc_currency or None,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "bank_details": (extracted.get("bank_details") or "").strip() or None,
            "line_count": len(extracted.get("line_totals") or []),
        },
    }
