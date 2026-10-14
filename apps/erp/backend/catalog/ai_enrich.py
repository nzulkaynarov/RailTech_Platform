"""AI #2 — PIM product enrichment (seller catalog assist).

When a seller creates/edits a catalog product, this DRAFTS a description, a list of key
specifications and PROPOSES the reference fields of the card — category, unit of measure,
ТН ВЭД code — from the product name (+ optional MPN / ГОСТ / domain). The result is a
SUGGESTION the seller reviews and accepts or rejects field by field (эталон — Akeneo AI
suggestions / Shopify Magic); it is NEVER auto-written to the catalog.

IRON RULE 1 (no hallucination): the model only drafts TEXT from the GIVEN input, and for
every reference field it only CHOOSES from a closed list we built from the database before
the call (`catalog/field_candidates.py`, `catalog/hs_suggest.py`). Every choice is then
verified against that same list deterministically — an invented Category id or unit code is
silent master-data corruption, and an invented ТН ВЭД code is found out at the border. It
must not invent prices, commitments, stock, or claim catalog facts as certain. The free-text
`suggested_category_hint` stays as the FALLBACK for when no candidate fits.

Gated behind `settings.AI_IMPORT_ENABLED`: returns {} (neutral) when disabled so the
seller's create/edit flow is never blocked or 500'd when AI is off. Reuses
`sourcing.services_ai._client()` + the Structured-Outputs json_schema config and logs
token usage exactly like the proven extract / match / preflight layers.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.conf import settings

from sourcing.services_ai import _client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProductFacts:
    """То, что о товаре сказал продавец (вход промпта)."""

    name: str
    domain_code: str | None = None
    mpn: str | None = None
    gost: str | None = None


@dataclass(frozen=True)
class _FieldCandidates:
    """Закрытые списки из базы, ИЗ КОТОРЫХ модель выбирает значения справочных полей."""

    hs: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    uoms: list[dict] = field(default_factory=list)


# Structured Outputs schema — all props required (additionalProperties=false forbids
# optional). specifications is a list of {key, value} pairs (matches Product.specifications
# JSON shape after the seller applies them). Справочные поля (hs_code_choice / category_id /
# uom_code) — это ВЫБОР из списка кандидатов в запросе, а suggested_category_hint остаётся
# свободным текстом-запаской (Rule 1: значения справочников мы не сочиняем).
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
        "hs_code_choice": {
            "type": "string",
            "description": (
                "Код ТН ВЭД, ВЫБРАННЫЙ из списка кандидатов в запросе — ровно как он там написан. "
                "'' если ни один не подходит или кандидатов не дали. НИКОГДА не сочиняй код."
            ),
        },
        "category_id": {
            "type": "integer",
            "description": (
                "id категории, ВЫБРАННЫЙ из списка кандидатов в запросе — ровно как он там написан. "
                "0, если ни одна не подходит или список не дали. НИКОГДА не придумывай id."
            ),
        },
        "uom_code": {
            "type": "string",
            "description": (
                "Код единицы измерения, ВЫБРАННЫЙ из списка в запросе — ровно как он там написан "
                "(напр. 'H87'). '' если список не дали или подходящей единицы в нём нет."
            ),
        },
    },
    "required": [
        "description",
        "specifications",
        "suggested_category_hint",
        "hs_code_choice",
        "category_id",
        "uom_code",
    ],
    "additionalProperties": False,
}

ENRICH_SYSTEM_PROMPT = (
    "Ты — ассистент наполнения каталога компании-поставщика (товары, материалы, "
    "оборудование, услуги для бизнеса). Продавец заводит карточку товара и даёт тебе "
    "наименование (и иногда артикул производителя, ГОСТ/чертёж, домен каталога). Твоя "
    "задача — ПРЕДЛОЖИТЬ черновик для ускорения заполнения карточки: краткое описание, "
    "список ключевых характеристик и значения справочных полей карточки.\n\n"
    "ПРАВИЛА:\n"
    "0. СПРАВОЧНЫЕ ПОЛЯ — ТОЛЬКО ВЫБОР ИЗ СПИСКА, НИКОГДА НЕ СОЧИНЕНИЕ. Это касается кода ТН ВЭД "
    "(hs_code_choice), категории (category_id) и единицы измерения (uom_code). Если в запросе дан "
    "список кандидатов — верни ОДИН из них ДОСЛОВНО, ровно как он там написан; если подходящего "
    "в списке нет или список не дали — верни пусто ('' для строк, 0 для category_id). Придуманное "
    "значение хуже пустого: код ТН ВЭД всплывёт ошибкой на таможне, чужой id категории уведёт "
    "карточку не в ту ветку каталога, чужая единица измерения исказит расчёт в КП. Пустое поле "
    "продавец заполнит сам за секунды — неверное он не заметит.\n"
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
    "Заполняй её всегда, когда понимаешь тип товара, — и особенно тогда, когда в списке "
    "категорий подходящей не нашлось (category_id=0): по этой подсказке продавец заведёт "
    "недостающую категорию. Если непонятно — пустая строка.\n"
    "6. Отвечай на русском языке.\n"
    "Верни результат строго по JSON-схеме."
)


def _build_user_message(facts: _ProductFacts, candidates: _FieldCandidates) -> str:
    """Render the seller-provided product facts as the prompt's user message. Only
    non-empty fields are included so the model is never fed phantom blanks to fill.

    Списки кандидатов приходят ИЗ БАЗЫ (retrieval), модель лишь выбирает — так справочные
    поля перестают быть генерацией. Справочник пуст → блока в промпте нет, и модель вернёт
    пустое значение: работа продавца не блокируется отсутствием данных."""
    parts = [f"Наименование товара: {facts.name}"]
    if facts.mpn:
        parts.append(f"Артикул производителя (MPN): {facts.mpn}")
    if facts.gost:
        parts.append(f"ГОСТ / чертёж: {facts.gost}")
    if facts.domain_code:
        parts.append(f"Домен каталога: {facts.domain_code}")
    if candidates.hs:
        listed = "\n".join(f"  {row['code']} — {row['name'][:120]}" for row in candidates.hs)
        parts.append("Кандидаты кода ТН ВЭД (выбери ОДИН дословно или верни пустую строку):\n" + listed)
    if candidates.categories:
        listed = "\n".join(f"  {row['id']} — {row['name'][:120]}" for row in candidates.categories)
        parts.append("Кандидаты категории каталога (верни id ОДНОЙ из них или 0):\n" + listed)
    if candidates.uoms:
        listed = "\n".join(f"  {row['code']} — {row['name'][:60]}" for row in candidates.uoms)
        parts.append("Единицы измерения (верни код ОДНОЙ из них дословно или пустую строку):\n" + listed)
    return (
        "Предложи черновик карточки для этого товара (описание, ключевые характеристики, "
        "подсказку категории, выбор кода ТН ВЭД, категории и единицы измерения):\n\n" + "\n".join(parts)
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

    Returns {description, specifications, suggested_category_hint, hs_code, hs_candidates,
    category_id, uom_code}. `category_id` / `uom_code` / `hs_code` are CHOICES verified against
    the DB-built candidate lists (never invented — Rule 1); `suggested_category_hint` stays as
    the free-text fallback for when no category candidate fits. Returns {} when AI is disabled
    or the name is empty (neutral — never raises, so the seller's create/edit flow is
    unaffected when AI is off).
    """
    name = (name or "").strip()
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not name:
        return {}

    # Кандидаты справочных полей берём ИЗ БАЗЫ до вызова модели (retrieval), чтобы она
    # выбирала, а не сочиняла. Справочник пуст → кандидатов нет → поле вернётся пустым.
    from catalog.field_candidates import category_candidates, uom_candidates
    from catalog.hs_suggest import suggest_hs_codes

    facts = _ProductFacts(
        name=name[:255],
        domain_code=(domain_code or "").strip() or None,
        mpn=(mpn or "").strip()[:120] or None,
        gost=(gost or "").strip()[:120] or None,
    )
    candidates = _FieldCandidates(
        hs=suggest_hs_codes(f"{facts.name} {facts.gost or ''} {facts.mpn or ''}".strip(), limit=8),
        categories=category_candidates(facts.name, domain_code=facts.domain_code),
        uoms=uom_candidates(),
    )

    user_msg = _build_user_message(facts, candidates)

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

    # Каждое справочное поле принимается, ТОЛЬКО если значение действительно было среди
    # кандидатов, которые мы же и передали: даже с прямым запретом в промпте модель может
    # вернуть «похожее» значение, а придуманное хуже пустого (ТН ВЭД всплывёт на границе,
    # чужой id уведёт карточку в другую ветку каталога). Сверка детерминированная.
    return {
        "description": str(data.get("description") or "").strip()[:4000],
        "specifications": _normalize_specifications(data.get("specifications")),
        # Свободный текст — ЗАПАСНОЙ вариант на случай, когда ни одна категория справочника
        # не подошла: по нему продавец заводит недостающую ветку.
        "suggested_category_hint": str(data.get("suggested_category_hint") or "").strip()[:200],
        "hs_code": _accepted_hs_code(data.get("hs_code_choice"), candidates.hs),
        "hs_candidates": candidates.hs,
        "category_id": _accepted_category_id(data.get("category_id"), candidates.categories),
        "uom_code": _accepted_uom_code(data.get("uom_code"), candidates.uoms),
    }


def _accepted_hs_code(choice, candidates: list[dict]) -> str:
    """Вернуть выбранный код, только если он есть в списке кандидатов; иначе пусто."""
    digits = "".join(ch for ch in str(choice or "") if ch.isdigit())
    if not digits:
        return ""
    allowed = {row["code"] for row in candidates or []}
    return digits if digits in allowed else ""


def _accepted_category_id(choice, candidates: list[dict]) -> int | None:
    """Вернуть выбранный id категории, только если он есть в списке кандидатов; иначе None.

    Ключевой случай — ЧУЖОЙ id: правдоподобное число (id категории другого домена или просто
    выдуманное) прошло бы в форму молча и увело карточку не в ту ветку каталога. 0 и любой
    нечисловой ответ — это «ничего не подошло»."""
    try:
        chosen = int(str(choice).strip())
    except (TypeError, ValueError):
        return None
    allowed = {row["id"] for row in candidates or []}
    return chosen if chosen in allowed else None


def _accepted_uom_code(choice, candidates: list[dict]) -> str:
    """Вернуть выбранный код единицы измерения, только если он есть в списке; иначе пусто.

    Сверка без учёта регистра, но возвращается КАНОНИЧЕСКИЙ код из справочника: 'h87' — это
    та же строка UN/ECE, а вот 'PCS' из головы модели — уже не наш справочник."""
    wanted = str(choice or "").strip().upper()
    if not wanted:
        return ""
    by_code = {str(row["code"]).upper(): row["code"] for row in candidates or []}
    return by_code.get(wanted, "")
