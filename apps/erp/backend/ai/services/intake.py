"""Разбор файла клиента в строки запроса (feature `intake`, алиас `intake-model`).

Клиент или сотрудник загружает ЛЮБОЙ файл (Excel / CSV / PDF / фото / текст) — модель
переносит позиции в каноническую схему строки (UBL/Peppol). Результат всегда проверяет
человек в редактируемой сетке, поэтому слой должен быть полезным, а не безупречным: промпт
запрещает выдумывать строки, большие таблицы режутся на куски (потолок вывода), коды единиц
сверяются со справочником в коде. Выключенный ИИ / слишком большой файл / все куски с ошибкой —
``RuntimeError`` с кодом: вызывающий уходит на детерминированный разбор.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .payloads import chunk_lines, file_to_payload
from .prompts import load_prompt

logger = logging.getLogger(__name__)

# Canonical request-line schema, aligned to UBL/Peppol line fields. All required
# (empty string / 0 when absent) — Structured Outputs forbids optional props with
# additionalProperties=false. `mpn`/`gost_drawing` let a line be identified WITHOUT a name.
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Наименование товара/материала/услуги (UBL Item/Name)"},
        "name_canonical": {
            "type": "string",
            "description": (
                "Каноническое РУССКОЕ наименование этой же позиции для поиска по каталогу: "
                "транслитерируй латиницу в кириллицу и приведи к словарной форме на русском "
                "(напр. 'podshipnik 6205' → 'Подшипник 6205', 'kabel VVG 3x2.5' → "
                "'Кабель ВВГ 3x2,5'). Бренды/модели/коды оставляй как есть. Если name уже на "
                "русском — продублируй его сюда. '' только если name пустой."
            ),
        },
        "quantity": {"type": "number", "description": "Количество (число; 1 если не указано)"},
        "unit": {"type": "string", "description": "Единица измерения как в файле (шт., м., дона, компл. …)"},
        "unit_code": {
            "type": "string",
            "description": "Код единицы из справочника UN/ECE Rec 20 (см. список в инструкции); '' если непонятно",
        },
        "mpn": {"type": "string", "description": "Артикул / код производителя (Manufacturer Part Number); '' если нет"},
        "gost_drawing": {
            "type": "string",
            "description": "Номер ГОСТ или чертежа детали (напр. 'ГОСТ 8752-79', '1-3242.00.00'); '' если нет. НЕ штрихкод.",
        },
        "note": {"type": "string", "description": "Спецификация/примечание/ссылка клиента (UBL line Note); иначе ''"},
    },
    "required": ["name", "name_canonical", "quantity", "unit", "unit_code", "mpn", "gost_drawing", "note"],
    "additionalProperties": False,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}},
    "required": ["items"],
    "additionalProperties": False,
}
MAX_OUTPUT_TOKENS = 8000


def unit_code_reference() -> tuple[set, str]:
    """Коды единиц из справочника (UN/ECE Rec 20) — источник истины, не словарь в коде."""
    from master_data.models import UnitOfMeasure

    rows = list(UnitOfMeasure.objects.filter(is_active=True).order_by("sort_order").values_list("code", "name"))
    return {code for code, _ in rows}, ", ".join(f"{code}={name}" for code, name in rows)


def _user_content(text: str | None, vision_block: dict | None) -> list[dict]:
    if vision_block is not None:
        return [vision_block, text_block("Извлеки позиции заявки из этого файла.")]
    return [text_block(f"Сырые данные из файла клиента:\n\n{text}")]


def extract_one(call: JsonCall) -> list[dict] | None:
    """Один вызов → сырые позиции. None — вызов не дал ответа (сеть/шлюз); [] — пустой ответ,
    отказ модели или непарсибельный JSON (как раньше: один плохой кусок не топит импорт)."""
    result = call_json(call)
    if result.status in ("error", "disabled"):
        return None
    if result.status == "truncated":
        logger.warning("AI extract: output truncated — lower AI_IMPORT_CHUNK_ROWS")
    if not result.ok:
        return []
    return result.data.get("items") or []


def normalize_items(items: list[dict], valid_codes: set) -> list[dict]:
    """Сырые позиции модели → чистые строки: количество ≥ 1, код единицы из справочника, длины
    под колонки БД, пустые строки (без имени и без кода) отброшены. Без I/O."""
    cleaned = []
    for raw_item in items:
        name = str(raw_item.get("name", "")).strip()
        name_canonical = str(raw_item.get("name_canonical", "")).strip()[:500] or name[:500]
        mpn = str(raw_item.get("mpn", "")).strip()[:120]
        gost_drawing = str(raw_item.get("gost_drawing", "")).strip()[:120]
        if not (name or mpn or gost_drawing):
            continue
        try:
            quantity = max(1, int(float(raw_item.get("quantity") or 1)))
        except (ValueError, TypeError):
            quantity = 1
        unit_code = str(raw_item.get("unit_code", "")).strip().upper()
        cleaned.append(
            {
                "name": name,
                "name_canonical": name_canonical,
                "quantity": quantity,
                "unit": str(raw_item.get("unit", "")).strip()[:32],
                "unit_code": unit_code if unit_code in valid_codes else "",
                "mpn": mpn,
                "gost_drawing": gost_drawing,
                "note": str(raw_item.get("note", "")).strip(),
            }
        )
    return cleaned


def _guard_file(content: bytes) -> None:
    if not settings.AI_IMPORT_ENABLED:
        raise RuntimeError("AI_IMPORT_DISABLED")
    max_bytes = getattr(settings, "AI_IMPORT_MAX_BYTES", 10 * 1024 * 1024)
    if len(content) > max_bytes:
        raise RuntimeError(f"AI_IMPORT_FILE_TOO_LARGE ({len(content)} > {max_bytes} bytes)")


def _extract_chunks(text: str, make_call) -> list[dict]:
    chunks = chunk_lines(text, settings.AI_IMPORT_CHUNK_ROWS)
    items: list[dict] = []
    failures = 0
    for index, chunk in enumerate(chunks):
        chunk_items = extract_one(make_call(_user_content(chunk, None)))
        if chunk_items is None:
            failures += 1
            logger.warning("AI extract: chunk %s/%s failed", index + 1, len(chunks))
            continue
        items.extend(chunk_items)
        logger.info(
            "AI extract: chunk %s/%s → %s items (total %s)", index + 1, len(chunks), len(chunk_items), len(items)
        )
    if chunks and failures == len(chunks):
        raise RuntimeError("AI_EXTRACT_ALL_CHUNKS_FAILED")
    return items


def extract_request_items(content: bytes, filename: str, *, retries: int | None = None) -> list[dict]:
    """Байты файла → строки `{name, name_canonical, quantity, unit, unit_code, mpn, gost_drawing, note}`.

    `retries` — повторы на сеть/5xx шлюза; по умолчанию ``AI_MAX_RETRIES`` (пакетный импорт идёт
    из Celery и может позволить себе backoff). ``RuntimeError`` с кодом — выключенный ИИ,
    слишком большой файл, недоступный шлюз (vision) или все куски с ошибкой.
    """
    _guard_file(content)
    valid_codes, code_guidance = unit_code_reference()
    prompt = load_prompt("intake")
    system = prompt.render(unit_codes=code_guidance)
    attempts = settings.AI_MAX_RETRIES if retries is None else retries
    text, vision_block = file_to_payload(content, filename)

    def make_call(user_content: list[dict]) -> JsonCall:
        return JsonCall(
            feature="intake",
            prompt=prompt,
            system=system,
            user_content=user_content,
            schema=RESULT_SCHEMA,
            max_tokens=MAX_OUTPUT_TOKENS,
            retries=attempts,
            mask_input=vision_block is not None,
        )

    if vision_block is not None:
        items = extract_one(make_call(_user_content(None, vision_block)))
        if items is None:
            raise RuntimeError("AI_GATEWAY_UNAVAILABLE")
    else:
        items = _extract_chunks(text, make_call)
    return normalize_items(items, valid_codes)
