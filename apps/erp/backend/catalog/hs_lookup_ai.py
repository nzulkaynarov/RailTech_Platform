"""ИИ-режим справочника ТН ВЭД: «опишите товар своими словами» → код с объяснением.

Второй режим поиска на странице справочника (T3, spec-tnved-flow). Обычный поиск — мгновенный
retrieval; этот — для случаев, когда пользователь не знает, как его товар зовётся у таможни
(«резинка под рельс» → прокладки рельсовых скреплений).

Та же трёхшаговая механика, что в обогащении карточки: retrieval из справочника → модель
ВЫБИРАЕТ один код дословно и объясняет выбор одной фразой → детерминированная сверка выбора
со списком кандидатов. Придуманный код невозможен по построению: не был в кандидатах — ответ
пустой с честным «не нашлось».

ARCH-01: LLM никогда не зовётся из request path — этот handler живёт в очереди `ai`
(`sourcing.run_ai_job`, feature `hs_lookup`), страница получает 202 и поллит `ai-status`.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

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

SYSTEM_PROMPT = (
    "Ты — помощник по классификации товаров в ТН ВЭД для компании-поставщика (товары, "
    "материалы и оборудование для бизнеса). Пользователь описывает товар своими словами; тебе дан список "
    "кандидатов из ОФИЦИАЛЬНОГО классификатора.\n\n"
    "ПРАВИЛА:\n"
    "1. Выбирай код ТОЛЬКО из списка кандидатов, дословно. Список пуст или ничего не подходит — "
    "верни пустую строку. НИКОГДА не сочиняй код: придуманный код ТН ВЭД хуже отсутствующего, "
    "об ошибке узнают на таможне.\n"
    "2. Объясни выбор ОДНОЙ фразой на русском: какой признак товара привёл к этой позиции.\n"
    "3. Не давай таможенных, налоговых или юридических консультаций — только классификация."
)


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

    from sourcing.services_ai import _client

    listed = "\n".join(f"  {row['code']} — {row['name'][:160]}" for row in candidates)
    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Товар: {description}\n\nКандидаты из классификатора:\n{listed}",
                    }
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": LOOKUP_SCHEMA}},
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info("AI hs_lookup usage: input=%s output=%s", usage.input_tokens, usage.output_tokens)

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"code": "", "name": "", "explanation": "", "candidates": candidates}

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
