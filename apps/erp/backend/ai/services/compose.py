"""Запрос из свободного текста (feature `compose`, алиас `intake-model`).

«Нужны подшипники 6205, 4 комплекта, и перчатки рабочие 40 пар» → строки запроса, которые
человек проверяет в сетке (ничего не отправляется само). Модель только извлекает сказанное;
привязка к каталогу — через `match_lines_to_catalog` (id только из шорт-листа БД). Выключенный
ИИ или пустой текст — `{"items": []}`, без исключений.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .errors import AIBudgetExceeded
from .gateway import JsonCall, call_json, text_block
from .matching import match_lines_to_catalog
from .prompts import load_prompt

logger = logging.getLogger(__name__)

COMPOSE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Наименование товара/услуги как сказал покупатель"},
        "name_canonical": {
            "type": "string",
            "description": (
                "Каноническое РУССКОЕ наименование этой же позиции для поиска по каталогу: "
                "транслитерируй латиницу в кириллицу и приведи к словарной форме на русском "
                "(напр. 'podshipnik 6205' → 'Подшипник 6205'). Бренды/модели/коды оставь "
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

#: Описание потребности — предложение, а не документ: вход модели ограничен.
MAX_TEXT_CHARS = 4000


def build_request_from_text(text: str, domain_code: str | None = None, attach_candidates: bool = True) -> dict:
    """Свободный текст → `{"items": [{name, name_canonical, quantity, unit, mpn, gost_drawing, note,
    candidates}]}`; `candidates` — подсказки каталога из `match_lines_to_catalog`."""
    cleaned = (text or "").strip()
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not cleaned:
        return {"items": []}
    prompt = load_prompt("compose")
    result = call_json(
        JsonCall(
            feature="compose",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block(f"Опиши потребность покупателя в позиции заявки:\n\n{cleaned[:MAX_TEXT_CHARS]}")],
            schema=COMPOSE_RESULT_SCHEMA,
            max_tokens=3000,
        )
    )
    if not result.ok:
        return {"items": []}
    items = normalise_items(result.data.get("items", []) or [])
    if items and attach_candidates:
        _attach_catalog_candidates(items, domain_code)
    return {"items": items}


def normalise_items(raw_items: list[dict]) -> list[dict]:
    """Ответ модели → чистые строки: без имени и без кода — шум, количество ≥ 1."""
    items: list[dict] = []
    for raw in raw_items:
        name = str(raw.get("name") or "").strip()
        mpn = str(raw.get("mpn") or "").strip()
        gost_drawing = str(raw.get("gost_drawing") or "").strip()
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
    """Подсказки каталога по строкам (best-effort: сбой или исчерпанный бюджет на этом шаге
    оставляют строки без подсказок, но не теряют сами строки)."""
    try:
        matches = match_lines_to_catalog(items, domain_code=domain_code)
    except (ValueError, KeyError, AIBudgetExceeded) as exc:
        logger.warning("AI compose: catalog match skipped (%s)", exc)
        return
    by_index = {match.get("line_index"): match.get("candidates", []) for match in matches}
    for index, item in enumerate(items):
        item["candidates"] = by_index.get(index, [])
