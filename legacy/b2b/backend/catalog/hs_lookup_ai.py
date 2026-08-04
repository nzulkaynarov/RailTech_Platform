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
    "Ты — помощник по классификации товаров в ТН ВЭД на B2B-площадке (железнодорожное и "
    "промышленное оборудование). Пользователь описывает товар своими словами; тебе дан список "
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
