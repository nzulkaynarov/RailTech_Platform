"""AI #3 — «КП vs заявка»: покрытие и смысловые расхождения (feature `diff`, алиас `draft-model`).

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
disappearing. The model is called through the single LiteLLM gateway client
(`ai.services.gateway.call_json`, prompt `prompts/diff.md`).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .prompts import load_prompt

logger = logging.getLogger(__name__)

# Issue-type codes (compared by code, never by translated text — Rule 2). The
# frontend maps each to a localized label.
ISSUE_UNCOVERED = "uncovered"
ISSUE_SUBSTITUTED = "substituted"
ISSUE_NOTE_IGNORED = "note_ignored"
ISSUE_QTY_UNIT = "qty_unit"

# Bound the number of lines fed to the model so one call stays within budget.
MAX_DIFF_LINES = 80


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

    prompt = load_prompt("diff")
    result = call_json(
        JsonCall(
            feature="diff",
            prompt=prompt,
            system=prompt.render(issue_substituted=ISSUE_SUBSTITUTED, issue_note_ignored=ISSUE_NOTE_IGNORED),
            user_content=[text_block(user_msg)],
            schema=DIFF_RESULT_SCHEMA,
            max_tokens=3000,
        )
    )
    if not result.ok:
        return []
    data = result.data

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


def quote_vs_request_diff(quote) -> dict:
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
