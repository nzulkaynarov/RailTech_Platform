"""AI #3 — «КП vs заявка» coverage / discrepancy check (advisory).

When a buyer has received a КП on their request, this surfaces a plain-language
summary of how the КП lines diverge from what was originally requested:

  * an UNCOVERED line — the seller did not price it (no product, zero price);
  * a SUBSTITUTED item — the seller priced a DIFFERENT catalog product than the
    buyer asked for by name;
  * a NOTE possibly IGNORED — the buyer's line note/spec carried a requirement the
    КП may not have honoured.

Two-layer design (Rule 1 — no hallucination):
  * The DETERMINISTIC layer (pure code, no AI) detects uncovered lines and the raw
    "the priced product name differs from the requested name" / "the line had a note"
    facts straight from the DB. These are always returned, even when AI is off.
  * The AI layer is asked ONLY the semantic questions a rule can't answer: *is this
    substitute an equivalent of what was requested?* and *was the note's requirement
    honoured?* The model may only COMMENT on lines we hand it (its `line` index is
    validated against the given range and out-of-range answers are dropped) — it can
    never invent a discrepancy on a line that does not exist.

The result is ASSISTIVE, never blocking: the buyer reads it and decides. Gated on
`settings.AI_IMPORT_ENABLED` — with AI off the deterministic findings still return,
so the feature degrades to "covered/uncovered + raw substitution facts" rather than
disappearing. Reuses the proven `sourcing.services_ai._client` Structured-Outputs
client (single Anthropic client, json_schema output, token-usage logging).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.conf import settings

from accounts.models import CustomUser

from ..models import Quote

logger = logging.getLogger(__name__)

# Issue-type codes (compared by code, never by translated text — Rule 2). The
# frontend maps each to a localized label.
ISSUE_UNCOVERED = "uncovered"
ISSUE_SUBSTITUTED = "substituted"
ISSUE_NOTE_IGNORED = "note_ignored"
ISSUE_QTY_UNIT = "qty_unit"

# Bound the number of lines fed to the model so one call stays within budget.
MAX_DIFF_LINES = 80


def _client():
    # Reuse the single, tested Anthropic client factory — one client, one config.
    from sourcing.services_ai import _client as ai_client

    return ai_client()


# Structured Outputs guarantee clean JSON (no preamble). The model only fills in
# the semantic verdicts for the lines we ask about.
DIFF_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {
                        "type": "integer",
                        "description": "Индекс строки из ДАННЫХ (0-based). ТОЛЬКО из переданных строк.",
                    },
                    "issue_type": {
                        "type": "string",
                        "enum": [ISSUE_SUBSTITUTED, ISSUE_NOTE_IGNORED],
                        "description": (
                            f"'{ISSUE_SUBSTITUTED}' — предложен НЕэквивалентный аналог; "
                            f"'{ISSUE_NOTE_IGNORED}' — требование из примечания заявки не учтено в КП"
                        ),
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Кратко на русском: в чём расхождение и почему это важно покупателю",
                    },
                },
                "required": ["line", "issue_type", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Ты — помощник покупателя на B2B-площадке (железнодорожное и промышленное оборудование). "
    "Покупатель отправил заявку, продавец прислал коммерческое предложение (КП). Тебе дают "
    "пронумерованные строки, где для каждой указано: ЧТО просил покупатель (наименование, "
    "примечание/требование) и ЧТО предложено в КП (наименование товара из каталога). Найди "
    "СМЫСЛОВЫЕ расхождения, которые формальная проверка не ловит.\n\n"
    "ОТМЕЧАЙ ТОЛЬКО:\n"
    f"1. '{ISSUE_SUBSTITUTED}' — в КП предложен товар, который НЕ является равноценным "
    "аналогом запрошенного (другой тип/марка/класс, несовместим). Если аналог эквивалентен — "
    "НЕ отмечай.\n"
    f"2. '{ISSUE_NOTE_IGNORED}' — в примечании заявки было конкретное требование (марка стали, "
    "ГОСТ, размер, «без замены», комплектность), а предложенный товар ему, судя по всему, не "
    "соответствует или его проигнорировали.\n\n"
    "ПРАВИЛА:\n"
    "1. КРИТИЧНО: line — ТОЛЬКО номер строки из переданных данных (0..N-1). НЕ придумывай "
    "строки и не ссылайся на несуществующие индексы.\n"
    "2. НИЧЕГО НЕ ВЫДУМЫВАЙ. Оценивай только то, что дано. Если расхождения нет — не добавляй "
    "находку для строки. Лучше пропустить сомнительное, чем выдумать.\n"
    "3. Не оценивай цены, сроки и непокрытые строки — это считается отдельно, не твоя задача.\n"
    "4. explanation — на русском, коротко и по делу.\n"
    "Верни результат строго по JSON-схеме."
)


def _requested_name(item) -> str:
    """What the buyer asked for, by name. The original request text lives in
    imported_raw_name (raw) / name_canonical (normalised); fall back across both."""
    return (item.imported_raw_name or "").strip() or (item.name_canonical or "").strip()


def _quoted_name(item) -> str:
    """What the КП actually priced — the linked catalog product's name."""
    if item.product_id and getattr(item, "product", None) is not None:
        return (item.product.name or "").strip()
    return ""


def _is_uncovered(item) -> bool:
    """Deterministic: the seller did not actually price this requested line.

    A line is uncovered when no catalog product was matched AND it carries no real
    price — the КП left it blank. (frozen_base_price / final_price are stored as 0
    on an un-worked line.)
    """
    if item.product_id:
        return False
    base = item.frozen_base_price or Decimal("0")
    final = item.final_price_excl_vat or Decimal("0")
    return base == 0 and final == 0


def _deterministic_findings(items) -> list[dict]:
    """Pure-code coverage facts — always returned, no AI. One finding per affected
    line: uncovered lines, and raw substitution facts (priced product name differs
    from the requested name). The AI layer later refines substitutions into
    equivalent-or-not and adds note-honoured verdicts."""
    findings: list[dict] = []
    for index, item in enumerate(items):
        if _is_uncovered(item):
            findings.append(
                {
                    "issue_type": ISSUE_UNCOVERED,
                    "line": index,
                    "explanation": "",  # localized in the UI from issue_type + line context
                }
            )
    return findings


def _build_ai_lines(items) -> list[dict]:
    """The per-line payload for the model: requested name + note vs the quoted
    product name. Only lines that were actually priced with a substitutable product
    (have both a requested name AND a quoted product) are worth a semantic verdict;
    uncovered lines are already handled deterministically."""
    lines = []
    for index, item in enumerate(items):
        requested = _requested_name(item)
        quoted = _quoted_name(item)
        note = (item.note or "").strip()
        # Need something to compare: a quoted product, plus either a requested name
        # or a note requirement to check it against.
        if quoted and (requested or note):
            lines.append(
                {
                    "line": index,
                    "requested": requested or "(без названия)",
                    "quoted": quoted,
                    "note": note,
                }
            )
    return lines


def _format_ai_lines(lines: list[dict]) -> str:
    blocks = []
    for entry in lines:
        parts = [f"Строка {entry['line']}: запрошено «{entry['requested']}»; " f"в КП предложено «{entry['quoted']}»"]
        if entry["note"]:
            parts.append(f"примечание заявки: {entry['note'][:300]}")
        blocks.append("; ".join(parts))
    return "\n".join(blocks)


def _semantic_findings(ai_lines: list[dict]) -> list[dict]:
    """Ask the model the equivalence / note-honoured questions for the given lines.

    Returns [] when AI is disabled, when there are no comparable lines, or on any
    refusal / unparseable response (never raises — the deterministic findings still
    stand). Each returned `line` is validated against the given indices (Rule 1)."""
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not ai_lines:
        return []

    bounded = ai_lines[:MAX_DIFF_LINES]
    valid_indices = {entry["line"] for entry in bounded}

    user_msg = f"Проверь {len(bounded)} строк (наименования заявки и КП).\n\n" + _format_ai_lines(bounded)

    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        output_config={"format": {"type": "json_schema", "schema": DIFF_RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info(
            "AI quote-diff usage: input=%s output=%s lines=%s",
            usage.input_tokens,
            usage.output_tokens,
            len(bounded),
        )
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("AI quote-diff: model declined (%s)", getattr(response, "stop_details", None))
        return []

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI quote-diff: unparseable JSON (len=%s)", len(raw or ""))
        return []

    findings: list[dict] = []
    for finding in data.get("findings", []) or []:
        line_index = finding.get("line")
        if line_index not in valid_indices:  # Rule 1: drop invented indices.
            continue
        issue_type = str(finding.get("issue_type") or "").strip().lower()
        if issue_type not in (ISSUE_SUBSTITUTED, ISSUE_NOTE_IGNORED):
            continue
        explanation = str(finding.get("explanation") or "").strip()[:500]
        if not explanation:
            continue
        findings.append({"issue_type": issue_type, "line": line_index, "explanation": explanation})
    return findings


def quote_vs_request_diff(quote: Quote) -> dict:
    """Coverage / discrepancy summary for a КП against its original request lines.

    Returns {"ai_enabled": bool, "findings": [{issue_type, line, explanation}]}.
    `findings` always includes the deterministic coverage facts (uncovered lines);
    when AI is enabled it is augmented with semantic verdicts (non-equivalent
    substitution, note possibly ignored). Each `line` is the 0-based index into the
    quote's items in their natural order, so the frontend can resolve it back to the
    requested/quoted names for display. NEVER raises for an empty/odd quote.
    """
    # position, then id — consistent with the grid / PDF / every other КП line ordering (S1). The
    # `line` index in findings is the 0-based offset into THIS order, so the frontend resolves it
    # back to the same row the seller sees.
    items = list(quote.items.select_related("product").order_by("position", "id"))
    if not items:
        return {"ai_enabled": bool(getattr(settings, "AI_IMPORT_ENABLED", False)), "findings": []}

    findings = _deterministic_findings(items)
    findings.extend(_semantic_findings(_build_ai_lines(items)))

    # Stable, deterministic ordering for the UI: by line, then issue_type.
    findings.sort(key=lambda finding: (finding["line"], finding["issue_type"]))
    return {
        "ai_enabled": bool(getattr(settings, "AI_IMPORT_ENABLED", False)),
        "findings": findings,
    }


def user_can_view_quote_diff(user: CustomUser, quote: Quote) -> bool:
    """Scope guard (Rule: only the deal's buyer or the routed seller). The diff is
    assistive read-only, so a platform admin viewer may also inspect it. Buyer =
    the deal's client OR an active member of the deal's company; seller = a can_sell
    company routed to the deal. Reuses the accounts permission helpers — no bespoke
    membership logic here.
    """
    from accounts.services.permissions import seller_company_routed_to_deal

    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    deal = quote.deal
    # Buyer side: the deal's contact user, or any active member of the buyer company.
    if deal.client_id == user.id:
        return True
    if deal.company_id and user.memberships.filter(company_id=deal.company_id, is_active=True).exists():
        return True
    # Seller side: a routed can_sell seller company.
    return seller_company_routed_to_deal(user, deal.pk)
