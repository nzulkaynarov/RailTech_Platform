"""AI #8 — conversational заявка builder.

The buyer describes a need in free text ("нужны тормозные колодки на вагон,
4 комплекта, и подшипники буксовые") and Claude turns it into STRUCTURED request
line items the buyer then reviews, edits and confirms in the editable grid
(human-in-loop — nothing is auto-submitted). This is the same idea as the
file-upload normaliser in ``services_ai`` but the input is a plain sentence
instead of a spreadsheet/scan.

IRON RULE 1 (no hallucination): the model only extracts what the buyer actually
said — it never invents extra positions, prices or specs. Product BINDINGS are
grounded in the REAL catalog by reusing ``match_lines_to_catalog`` (DB trigram
shortlist → Claude ranks → ids always come from the DB, never the model). The
buyer confirms a candidate in the grid, so this layer only has to be useful.

Gated behind ``settings.AI_IMPORT_ENABLED``: returns an empty item list when
disabled (no API key) — never raises, so the buyer flow is unaffected when AI is
off. Reuses ``services_ai._client()`` + the Structured-Outputs json_schema config
and logs token usage exactly like the proven extract/match layers.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from .services_ai import _client, match_lines_to_catalog

logger = logging.getLogger(__name__)

# Structured Outputs schema — one proposed line per array element. Mirrors the
# ITEM_SCHEMA shape in services_ai (UBL/Peppol line fields) but trimmed to the
# fields the buyer fills in the request grid. All props required (Structured
# Outputs forbids optional props under additionalProperties=false): use "" / 0
# when a value was not stated.
COMPOSE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Наименование товара/материала как сказал покупатель"},
        "name_canonical": {
            "type": "string",
            "description": (
                "Каноническое РУССКОЕ наименование этой же позиции для поиска по каталогу: "
                "транслитерируй латиницу в кириллицу и приведи к словарной форме на русском "
                "(напр. 'tormoznaya koloda' → 'Тормозная колодка'). Бренды/модели/коды оставь "
                "как есть. Если name уже на русском — продублируй его сюда. '' только если name пустой."
            ),
        },
        "quantity": {"type": "number", "description": "Количество (число; 1 если не указано)"},
        "unit": {
            "type": "string",
            "description": "Единица измерения как сказал покупатель (шт., компл., м. …); '' если не указано",
        },
        "mpn": {"type": "string", "description": "Артикул / код производителя, если упомянут; '' если нет"},
        "gost_drawing": {
            "type": "string",
            "description": "Номер ГОСТ или чертежа, если упомянут (напр. 'ГОСТ 8752-79'); '' если нет. НЕ штрихкод.",
        },
        "note": {
            "type": "string",
            "description": "Доп. требования/уточнения покупателя (срок, замена, параметры); иначе ''",
        },
    },
    "required": ["name", "name_canonical", "quantity", "unit", "mpn", "gost_drawing", "note"],
    "additionalProperties": False,
}
COMPOSE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": COMPOSE_ITEM_SCHEMA}},
    "required": ["items"],
    "additionalProperties": False,
}

COMPOSE_SYSTEM_PROMPT = (
    "Ты — ассистент составления заявки на закупку для B2B-площадки (железнодорожное и "
    "промышленное оборудование, материалы). Покупатель описывает свою потребность ОБЫЧНЫМ "
    "ТЕКСТОМ (одно-два предложения), а ты разбиваешь её на отдельные позиции заявки.\n\n"
    "ПРАВИЛА:\n"
    "1. Для каждой упомянутой позиции верни: name (наименование), quantity (количество, число; "
    "1 если не сказано), unit (единица измерения как сказал покупатель: шт., компл., м.; '' если "
    "не сказано), mpn (артикул/код, если упомянут), gost_drawing (ГОСТ/чертёж, если упомянут — "
    "НЕ штрихкод), note (доп. требования: срок, допустимость замены, параметры).\n"
    "2. name делай ЛАКОНИЧНЫМ коммерческим названием (тип + ключевые параметры, 2–8 слов). "
    "Длинные уточнения переноси в note.\n"
    "3. Каждую отдельную потребность — отдельной строкой. «Тормозные колодки и подшипники» — "
    "это ДВЕ позиции.\n"
    "4. НИЧЕГО НЕ ВЫДУМЫВАЙ. Если покупатель не назвал количество/единицу/код — оставь '' или 1. "
    "НЕ добавляй позиции, которых нет в тексте. НЕ придумывай цены, бренды или характеристики, "
    "которые покупатель не упомянул.\n"
    "5. name оставляй на языке покупателя; в name_canonical верни каноническое РУССКОЕ "
    "наименование той же позиции (транслитерация латиницы в кириллицу + словарная форма) для "
    "поиска по каталогу — бренды, модели и коды при этом не переводи.\n"
    "6. Если текст вообще не про закупку (приветствие, вопрос) — верни пустой список позиций.\n"
    "Верни результат строго по заданной JSON-схеме."
)

# Hard cap on the input the model sees — a request description is a sentence, not a
# document; clamp to keep one Claude call bounded and cheap.
MAX_TEXT_CHARS = 4000


def build_request_from_text(
    text: str,
    domain_code: str | None = None,
    attach_candidates: bool = True,
) -> dict:
    """Turn a free-text need into proposed заявка line items (human reviews after).

    Returns ``{"items": [{name, name_canonical, quantity, unit, mpn, gost_drawing,
    note, candidates}]}``. ``candidates`` is a list of catalog Product suggestions
    (``[{product_id, name, sku, confidence, reason}]``) grounded in the REAL catalog
    via :func:`match_lines_to_catalog` (ids always from a DB shortlist — never
    invented). Returns ``{"items": []}`` when AI is disabled or the text is empty —
    never raises, so the buyer flow is unaffected when AI is off.
    """
    cleaned = (text or "").strip()
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not cleaned:
        return {"items": []}

    bounded = cleaned[:MAX_TEXT_CHARS]
    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=3000,
        system=COMPOSE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": f"Опиши потребность покупателя в позиции заявки:\n\n{bounded}"}],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": COMPOSE_RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        # Log token spend — this is a paid Claude call, keep it observable.
        logger.info("AI compose usage: input=%s output=%s", usage.input_tokens, usage.output_tokens)
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("AI compose: model declined (%s)", getattr(response, "stop_details", None))
        return {"items": []}

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI compose: unparseable JSON (len=%s)", len(raw or ""))
        return {"items": []}

    items = _normalise_items(data.get("items", []) or [])
    if items and attach_candidates:
        _attach_catalog_candidates(items, domain_code)
    return {"items": items}


def _normalise_items(raw_items: list[dict]) -> list[dict]:
    """Coerce model output into clean request lines. Drops empty rows (no name AND
    no code — nothing for a human to act on), clamps quantity to a sane minimum."""
    items: list[dict] = []
    for raw in raw_items:
        name = str(raw.get("name") or "").strip()
        mpn = str(raw.get("mpn") or "").strip()
        gost_drawing = str(raw.get("gost_drawing") or "").strip()
        # A line with neither a name nor any identifying code is noise — skip it.
        if not name and not mpn and not gost_drawing:
            continue
        try:
            quantity = max(1, int(float(raw.get("quantity") or 1)))
        except (TypeError, ValueError):
            quantity = 1
        items.append(
            {
                "name": name,
                "name_canonical": str(raw.get("name_canonical") or "").strip(),
                "quantity": quantity,
                "unit": str(raw.get("unit") or "").strip(),
                "mpn": mpn,
                "gost_drawing": gost_drawing,
                "note": str(raw.get("note") or "").strip()[:1000],
                "candidates": [],
            }
        )
    return items


def _attach_catalog_candidates(items: list[dict], domain_code: str | None) -> None:
    """Ground each proposed line in the REAL catalog (Rule 1). Mutates items in
    place, filling ``candidates`` from :func:`match_lines_to_catalog` (ids from a
    DB trigram shortlist — never invented). Best-effort: a match failure leaves
    candidates empty rather than sinking the compose result."""
    try:
        matches = match_lines_to_catalog(items, domain_code=domain_code)
    except (ValueError, KeyError) as exc:  # match is best-effort, never block compose
        logger.warning("AI compose: catalog match skipped (%s)", exc)
        return
    by_index = {match.get("line_index"): match.get("candidates", []) for match in matches}
    for index, item in enumerate(items):
        item["candidates"] = by_index.get(index, [])
