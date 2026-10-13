"""AI #7 — pre-flight заявка quality check (advisory).

Before a buyer submits an RFQ, Claude does an ADVISORY pass over the request
lines and flags quality issues a rule-based gate can't catch on its own: vague
descriptions, missing / implausible quantity or units, likely-duplicate lines,
or a missing key spec. These are WARNINGS the buyer reviews — never a hard block
(the request can still be submitted with warnings present).

IRON RULE 1 (no hallucination): every returned `line_index` MUST reference a
line that was GIVEN in the input. The model is told the valid index range and
we additionally drop any out-of-range index after the fact — the AI may only
FLAG given lines, never invent new ones or new rows.

Gated behind `settings.AI_IMPORT_ENABLED`: returns [] (neutral, no warnings)
when disabled — never raises, so the buyer flow is unaffected when AI is off.
Reuses `services_ai._client()` + the Structured-Outputs json_schema config and
logs token usage exactly like the proven extract/match layers.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from .services_ai import _client

logger = logging.getLogger(__name__)

# Structured Outputs schema — one advisory finding per array element. All props
# required (additionalProperties=false forbids optional). severity is constrained
# to the two advisory levels; we never emit a hard "error" level (Rule: advisory).
PREFLIGHT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_index": {
                        "type": "integer",
                        "description": "Индекс строки из ДАННЫХ (0-based). ТОЛЬКО из переданных строк.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning"],
                        "description": "warning — стоит исправить; info — мелкое замечание",
                    },
                    "issue": {"type": "string", "description": "Что не так со строкой (кратко)"},
                    "suggestion": {"type": "string", "description": "Как улучшить (конкретно)"},
                },
                "required": ["line_index", "severity", "issue", "suggestion"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

PREFLIGHT_SYSTEM_PROMPT = (
    "Ты — ассистент проверки качества заявки на закупку для B2B-площадки "
    "(железнодорожное и промышленное оборудование, материалы). Тебе дают пронумерованные "
    "строки заявки, которые покупатель собирается отправить поставщикам. Твоя задача — найти "
    "проблемы качества, которые помешают поставщику дать точное предложение, и вернуть их как "
    "СОВЕТЫ (не блокировку).\n\n"
    "ИЩИ:\n"
    "1. Расплывчатое/неинформативное наименование («труба», «болт», «запчасть») — без типа, "
    "размера, марки.\n"
    "2. Отсутствует или неправдоподобно количество (0, пусто, абсурдно большое).\n"
    "3. Отсутствует или сомнительная единица измерения для такого товара.\n"
    "4. Похоже на дубликат другой строки (та же позиция повторяется) — укажи одну из строк.\n"
    "5. Нет ключевой характеристики (размер/марка стали/ГОСТ/мощность), без которой нельзя "
    "однозначно подобрать товар.\n\n"
    "ПРАВИЛА:\n"
    "1. КРИТИЧНО: line_index — ТОЛЬКО номер строки из переданных данных (0..N-1). НЕ придумывай "
    "новые строки и НЕ ссылайся на несуществующие индексы.\n"
    "2. severity: 'warning' если стоит исправить до отправки; 'info' — мелочь.\n"
    "3. НИЧЕГО НЕ ВЫДУМЫВАЙ про содержимое строки — оценивай только то, что дано. Если строка "
    "нормальная — не добавляй для неё находку.\n"
    "4. Это советы, а не запрет: не будь придирчивым, отмечай только реальные проблемы.\n"
    "5. issue и suggestion — на русском, коротко и конкретно.\n"
    "Верни результат строго по JSON-схеме."
)

# Hard cap mirrors the endpoint line cap — keeps one Claude call bounded.
MAX_PREFLIGHT_LINES = 50


def _format_lines(lines: list[dict]) -> str:
    """Render the given request lines as a numbered block for the prompt. The
    indices here are the ONLY valid `line_index` values the model may return."""
    blocks = []
    for index, line in enumerate(lines):
        name = str(line.get("name") or "").strip() or "(без названия)"
        parts = [f"Строка {index}: {name}"]
        quantity = line.get("quantity")
        unit = str(line.get("unit") or "").strip()
        parts.append(f"кол-во={quantity if quantity not in (None, '') else '—'}")
        parts.append(f"ед.={unit or '—'}")
        mpn = str(line.get("mpn") or "").strip()
        if mpn:
            parts.append(f"артикул={mpn}")
        gost = str(line.get("gost_drawing") or "").strip()
        if gost:
            parts.append(f"ГОСТ/чертёж={gost}")
        note = str(line.get("note") or "").strip()
        if note:
            parts.append(f"прим.={note[:200]}")
        blocks.append("; ".join(parts))
    return "\n".join(blocks)


def pre_flight_check(lines: list[dict], domain_code: str | None = None) -> list[dict]:
    """Advisory quality pass over заявка lines → list of findings.

    Returns [{line_index, severity, issue, suggestion}], each `line_index`
    guaranteed to reference a GIVEN line (out-of-range dropped — Rule 1).
    Returns [] when AI disabled or no lines (neutral — never raises so the
    buyer submit flow is unaffected).
    """
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not lines:
        return []

    bounded = lines[:MAX_PREFLIGHT_LINES]
    valid_indices = set(range(len(bounded)))

    domain_hint = f" Предметная область заявки: {domain_code}." if domain_code else ""
    user_msg = f"Проверь {len(bounded)} строк заявки (индексы 0..{len(bounded) - 1}).{domain_hint}\n\n" + _format_lines(
        bounded
    )

    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=3000,
        system=PREFLIGHT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        output_config={"format": {"type": "json_schema", "schema": PREFLIGHT_RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        # Log token spend — this is a paid Claude call, keep it observable.
        logger.info(
            "AI preflight usage: input=%s output=%s lines=%s",
            usage.input_tokens,
            usage.output_tokens,
            len(bounded),
        )
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("AI preflight: model declined (%s)", getattr(response, "stop_details", None))
        return []

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI preflight: unparseable JSON (len=%s)", len(raw or ""))
        return []

    findings: list[dict] = []
    for finding in data.get("findings", []) or []:
        line_index = finding.get("line_index")
        # Rule 1: drop any index the model invented that is not in the GIVEN input.
        if line_index not in valid_indices:
            continue
        severity = str(finding.get("severity") or "warning").strip().lower()
        if severity not in ("info", "warning"):
            severity = "warning"
        issue = str(finding.get("issue") or "").strip()[:300]
        if not issue:
            continue
        findings.append(
            {
                "line_index": line_index,
                "severity": severity,
                "issue": issue,
                "suggestion": str(finding.get("suggestion") or "").strip()[:300],
            }
        )
    return findings
