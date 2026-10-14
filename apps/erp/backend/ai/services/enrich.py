"""AI #2 — черновик карточки товара/услуги (feature `enrich`, алиас `enrich-model`).

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
seller's create/edit flow is never blocked or 500'd when AI is off. Calls the
model through the single LiteLLM gateway client (`ai.services.gateway.call_json`); the
system prompt is `prompts/enrich.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .prompts import load_prompt

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
            "description": "Текстовая ПОДСКАЗКА вероятной категории (напр. 'Электрооборудование'). НЕ id. '' если непонятно.",
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

    prompt = load_prompt("enrich")
    result = call_json(
        JsonCall(
            feature="enrich",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block(user_msg)],
            schema=ENRICH_RESULT_SCHEMA,
            max_tokens=2000,
        )
    )
    if not result.ok:
        return {}
    data = result.data

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
