"""ИИ-режим справочника ТН ВЭД: «опишите товар своими словами» → код с объяснением.

Второй режим поиска на странице справочника (T3, spec-tnved-flow). Обычный поиск — мгновенный
retrieval; этот — для случаев, когда пользователь не знает, как его товар зовётся у таможни
(«шнур для зарядки телефона» → кабели с соединителями).

Та же трёхшаговая механика, что в обогащении карточки: retrieval из справочника → модель
ВЫБИРАЕТ один код дословно и объясняет выбор одной фразой → детерминированная сверка выбора
со списком кандидатов. Придуманный код невозможен по построению: не был в кандидатах — ответ
пустой с честным «не нашлось».

ARCH-01: LLM никогда не зовётся из request path — этот handler живёт в очереди `ai`
(`sourcing.run_ai_job`, feature `hs_lookup`), страница получает 202 и поллит `ai-status`.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .prompts import load_prompt

logger = logging.getLogger(__name__)

LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "hs_code_choice": {
            "type": "string",
            "description": "Код из списка кандидатов ДОСЛОВНО, либо '' если ни один не подходит.",
        },
        "explanation": {
            "type": "string",
            "description": "Одна фраза: почему выбран этот код (или почему ничего не подошло). На русском.",
        },
    },
    "required": ["hs_code_choice", "explanation"],
    "additionalProperties": False,
}


def lookup_hs_code(description: str) -> dict:
    """`{code, name, explanation, candidates}` по свободному описанию товара.

    Пустой справочник или отключённый AI → пустой код с кандидатами (страница честно предложит
    обычный поиск). Никогда не бросает наружу.
    """
    from catalog.hs_suggest import suggest_hs_codes

    description = (description or "").strip()[:500]
    if not description:
        return {"code": "", "name": "", "explanation": "", "candidates": []}

    candidates = suggest_hs_codes(description, limit=10)
    if not candidates or not getattr(settings, "AI_IMPORT_ENABLED", False):
        return {"code": "", "name": "", "explanation": "", "candidates": candidates}

    listed = "\n".join(f"  {row['code']} — {row['name'][:160]}" for row in candidates)
    prompt = load_prompt("hs_lookup")
    result = call_json(
        JsonCall(
            feature="hs",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block(f"Товар: {description}\n\nКандидаты из классификатора:\n{listed}")],
            schema=LOOKUP_SCHEMA,
            max_tokens=500,
        )
    )
    if not result.ok:
        return {"code": "", "name": "", "explanation": "", "candidates": candidates}
    data = result.data

    # Детерминированная сверка: выбор принимается, только если он был среди кандидатов.
    digits = "".join(ch for ch in str(data.get("hs_code_choice") or "") if ch.isdigit())
    chosen = next((row for row in candidates if row["code"] == digits), None)
    return {
        "code": chosen["code"] if chosen else "",
        "name": chosen["name"] if chosen else "",
        "explanation": str(data.get("explanation") or "").strip()[:500],
        "candidates": candidates,
    }


def classify_products(product_ids: list[int], user_id: int | None = None) -> dict:
    """Пакетный подбор кодов ТН ВЭД для карточек (T4, паттерн Avalara bulk classification).

    Для каждой карточки без действующего кода: retrieval по имени+ГОСТ+артикулу → модель
    выбирает из кандидатов → детерминированная сверка. Предложение НЕ применяется молча —
    результат возвращается со статусом `suggested`, карточка меняется только после
    подтверждения человеком (Avalara/Zonos: у классификации всегда есть подтверждающий).

    Работает и без AI: тогда предлагается лучший retrieval-кандидат с score ≥ 0.5 — честный
    детерминированный фолбэк, тоже под подтверждение.
    """
    from catalog.models import Product

    results: list[dict] = []
    cards = Product.objects.filter(pk__in=product_ids[:100]).select_related("status")
    for card in cards:
        query = " ".join(
            part for part in [card.name, card.gost_drawing or "", card.manufacturer_part_number or ""] if part
        ).strip()
        outcome = lookup_hs_code(query)
        suggested = outcome["code"]
        explanation = outcome["explanation"]
        if not suggested and outcome["candidates"]:
            top = outcome["candidates"][0]
            if float(top.get("score") or 0) >= 0.5:
                suggested = top["code"]
                explanation = ""
        results.append(
            {
                "product_id": card.pk,
                "name": card.name[:120],
                "current_code": card.hs_code or "",
                "suggested_code": suggested,
                "suggested_name": outcome["name"]
                or next((c["name"] for c in outcome["candidates"] if c["code"] == suggested), ""),
                "explanation": explanation,
            }
        )
    return {"results": results}
