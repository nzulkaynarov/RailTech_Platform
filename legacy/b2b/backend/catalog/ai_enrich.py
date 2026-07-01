"""AI #2 — PIM product enrichment (seller catalog assist).

When a seller creates/edits a catalog product, this DRAFTS a description, a list
of key specifications, and a likely-category HINT from the product name (+ optional
MPN / ГОСТ / domain). The result is a SUGGESTION the seller reviews and edits before
saving — it is NEVER auto-written to the catalog.

IRON RULE 1 (no hallucination): the model only drafts text from the GIVEN input. It
must not invent prices, commitments, stock, or claim catalog facts as certain. The
category is returned as a free-text HINT string only — we deliberately do NOT resolve
or invent a Category id (the seller picks the real category from the DB dropdown).

Gated behind `settings.AI_IMPORT_ENABLED`: returns {} (neutral) when disabled so the
seller's create/edit flow is never blocked or 500'd when AI is off. Reuses
`sourcing.services_ai._client()` + the Structured-Outputs json_schema config and logs
token usage exactly like the proven extract / match / preflight layers.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from sourcing.services_ai import _client

logger = logging.getLogger(__name__)

# Structured Outputs schema — all props required (additionalProperties=false forbids
# optional). specifications is a list of {key, value} pairs (matches Product.specifications
# JSON shape after the seller applies them). suggested_category_hint is a plain string —
# a HINT, never an id (Rule 1: we never invent a Category primary key).
ENRICH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "Сжатое товарное описание для каталога (2–4 предложения). '' если данных мало.",
        },
        "specifications": {
            "type": "array",
            "description": "Ключевые технические характеристики, выводимые из наименования/артикула. Пусто, если нечего вывести.",
            "items": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Название характеристики (напр. 'Материал', 'Напряжение')",
                    },
                    "value": {"type": "string", "description": "Значение характеристики (напр. 'Сталь 45', '24 В')"},
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        "suggested_category_hint": {
            "type": "string",
            "description": "Текстовая ПОДСКАЗКА вероятной категории (напр. 'Тормозное оборудование'). НЕ id. '' если непонятно.",
        },
    },
    "required": ["description", "specifications", "suggested_category_hint"],
    "additionalProperties": False,
}

ENRICH_SYSTEM_PROMPT = (
    "Ты — ассистент наполнения каталога B2B-площадки (железнодорожное и промышленное "
    "оборудование, материалы, услуги). Продавец заводит карточку товара и даёт тебе "
    "наименование (и иногда артикул производителя, ГОСТ/чертёж, домен каталога). Твоя "
    "задача — ПРЕДЛОЖИТЬ черновик для ускорения заполнения карточки: краткое описание, "
    "список ключевых характеристик и текстовую подсказку вероятной категории.\n\n"
    "ПРАВИЛА:\n"
    "1. КРИТИЧНО — НИЧЕГО НЕ ВЫДУМЫВАЙ. Выводи только то, что обоснованно следует из данных "
    "продавца и общеизвестных свойств такого типа товара. НЕ придумывай цены, наличие, сроки, "
    "сертификаты, гарантии или конкретные числовые параметры, которых нет во входных данных и "
    "которые нельзя достоверно вывести из наименования/артикула.\n"
    "2. Это ПРЕДЛОЖЕНИЕ, которое продавец проверит и отредактирует перед сохранением. Лучше "
    "оставить поле пустым ('' или пустой список), чем заполнить его догадкой.\n"
    "3. description — сжатое товарное описание (2–4 предложения), нейтральным деловым тоном, "
    "без рекламных преувеличений и без обещаний.\n"
    "4. specifications — список пар ключ/значение, только характеристики, которые явно "
    "читаются из наименования/артикула/ГОСТ (тип, типоразмер, материал, номинал…). Если "
    "достоверно вывести нельзя — не добавляй характеристику.\n"
    "5. suggested_category_hint — короткая ТЕКСТОВАЯ подсказка категории (НЕ код, НЕ id). "
    "Если непонятно — пустая строка.\n"
    "6. Отвечай на русском языке.\n"
    "Верни результат строго по JSON-схеме."
)


def _build_user_message(name: str, domain_code: str | None, mpn: str | None, gost: str | None) -> str:
    """Render the seller-provided product facts as the prompt's user message. Only
    non-empty fields are included so the model is never fed phantom blanks to fill."""
    parts = [f"Наименование товара: {name}"]
    if mpn:
        parts.append(f"Артикул производителя (MPN): {mpn}")
    if gost:
        parts.append(f"ГОСТ / чертёж: {gost}")
    if domain_code:
        parts.append(f"Домен каталога: {domain_code}")
    return (
        "Предложи черновик карточки для этого товара (описание, ключевые характеристики, "
        "подсказку категории):\n\n" + "\n".join(parts)
    )


def _normalize_specifications(raw_specs) -> list[dict]:
    """Pure post-processing of the model's raw specs → clean {key, value} rows.

    Drops rows without a key, trims to sane lengths, and caps the count so a runaway
    response can't bloat the card. No I/O — unit-testable directly."""
    cleaned: list[dict] = []
    for raw_spec in raw_specs or []:
        if not isinstance(raw_spec, dict):
            continue
        key = str(raw_spec.get("key") or "").strip()[:100]
        value = str(raw_spec.get("value") or "").strip()[:300]
        if not key:
            continue
        cleaned.append({"key": key, "value": value})
        if len(cleaned) >= 30:
            break
    return cleaned


def enrich_product(
    name: str,
    domain_code: str | None = None,
    mpn: str | None = None,
    gost: str | None = None,
) -> dict:
    """Draft catalog fields for a product from its name (+ optional MPN/ГОСТ/domain).

    Returns {description, specifications: [{key, value}], suggested_category_hint}.
    The category is a HINT string only — never a resolved id (Rule 1). Returns {}
    when AI is disabled or the name is empty (neutral — never raises, so the seller's
    create/edit flow is unaffected when AI is off).
    """
    name = (name or "").strip()
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not name:
        return {}

    user_msg = _build_user_message(
        name[:255],
        (domain_code or "").strip() or None,
        (mpn or "").strip()[:120] or None,
        (gost or "").strip()[:120] or None,
    )

    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=2000,
        system=ENRICH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        output_config={"format": {"type": "json_schema", "schema": ENRICH_RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        # Log token spend — this is a paid Claude call, keep it observable.
        logger.info("AI enrich usage: input=%s output=%s", usage.input_tokens, usage.output_tokens)
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("AI enrich: model declined (%s)", getattr(response, "stop_details", None))
        return {}

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI enrich: unparseable JSON (len=%s)", len(raw or ""))
        return {}

    return {
        "description": str(data.get("description") or "").strip()[:4000],
        "specifications": _normalize_specifications(data.get("specifications")),
        # Rule 1: a HINT string only — we never invent or resolve a Category id here.
        "suggested_category_hint": str(data.get("suggested_category_hint") or "").strip()[:200],
    }
