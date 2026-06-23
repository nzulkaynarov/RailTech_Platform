"""AI заявка normalisation — client uploads ANY file, Claude maps it to our schema.

The buyer ALWAYS reviews the result in the editable request grid before
submitting (the AI never writes a final заявка unattended), so this layer only
has to be *useful*, not perfect. Hallucinations are caught at review; the system
prompt still forbids inventing rows. Large specs are chunked to stay within the
output-token budget. Structured Outputs guarantee clean JSON (no "Конечно, вот…").

Falls back to nothing: callers should use the deterministic parser in tasks.py
when `settings.AI_IMPORT_ENABLED` is False (no API key).
"""

from __future__ import annotations

import base64
import json
import logging
from io import BytesIO

import pandas as pd
from django.conf import settings

logger = logging.getLogger(__name__)

# Canonical request-line schema, aligned to UBL/Peppol line fields. All required
# (empty string / 0 when absent) — Structured Outputs forbids optional props with
# additionalProperties=false. `mpn`/`gost_drawing` let a line be identified WITHOUT a name.
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Наименование товара/материала (UBL Item/Name)"},
        "quantity": {"type": "number", "description": "Количество (число; 1 если не указано)"},
        "unit": {"type": "string", "description": "Единица измерения как в файле (шт., м., дона, компл. …)"},
        "unit_code": {"type": "string", "description": "Код единицы из справочника UN/ECE Rec 20 (см. список в инструкции); '' если непонятно"},
        "mpn": {"type": "string", "description": "Артикул / код производителя (Manufacturer Part Number); '' если нет"},
        "gost_drawing": {
            "type": "string",
            "description": "Номер ГОСТ или чертежа детали (напр. 'ГОСТ 8752-79', '1-3242.00.00'); '' если нет. НЕ штрихкод.",
        },
        "note": {"type": "string", "description": "Спецификация/примечание/ссылка клиента (UBL line Note); иначе ''"},
    },
    "required": ["name", "quantity", "unit", "unit_code", "mpn", "gost_drawing", "note"],
    "additionalProperties": False,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}},
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Ты — парсер заявок на закупку для B2B-площадки (железнодорожное и промышленное "
    "оборудование, материалы). На вход поступают СЫРЫЕ данные из файла клиента: таблица, "
    "свободный текст или изображение/скан. Твоя задача — извлечь позиции, которые клиент "
    "хочет закупить.\n\n"
    "ПРАВИЛА:\n"
    "1. Для каждой позиции верни: name (наименование), quantity (количество, число), "
    "unit (единица измерения как в файле), mpn (артикул / код производителя, если есть), "
    "gost_drawing (номер ГОСТ или чертежа детали, если есть — НЕ штрихкод), note (описание/спецификация).\n"
    "2. name делай ЛАКОНИЧНЫМ — это коммерческое название позиции: тип + бренд + модель + "
    "ключевые параметры (обычно 3–8 слов). Длинное техническое описание НЕ оставляй в name — "
    "перенеси его в note. Пример: из «Компактный однофазный стабилизированный импульсный блок "
    "питания на DIN-рейку Siemens SITOP PSU100C 24 V / 4 A» сделай name = «Блок питания Siemens "
    "SITOP PSU100C 24V/4A», note = «Компактный однофазный стабилизированный импульсный, монтаж на "
    "DIN-рейку». В note также клади доп. требования («допускается замена», «вход 2×4-20mA») и ссылку, "
    "если есть. Ничего из исходных данных не теряй: что не попало в name/mpn — должно остаться в note.\n"
    "3. Если в наименовании зашит артикул/код (например «ДПС-У-09 ПЮЯИ.468179.001-09»), вынеси "
    "код в mpn, а в name оставь читаемое наименование.\n"
    "4. ИГНОРИРУЙ строки-заголовки таблицы, заголовок документа, нумерацию, итоги, пустые "
    "строки и служебные колонки (например «Фото»/«Photo» — это вложение, а не данные).\n"
    "5. НИЧЕГО НЕ ВЫДУМЫВАЙ. Если значения нет в файле — для строк оставь пустую строку, для "
    "quantity поставь 1. НЕ добавляй позиции, которых нет в данных. Лучше пропустить "
    "сомнительное, чем выдумать. Позицию можно вернуть и без name, если есть mpn или gost_drawing "
    "(её потом дозаполнит человек).\n"
    "6. Языки могут быть любыми (рус./узб./англ.). Наименование оставляй как в оригинале.\n"
    "Верни результат строго по заданной JSON-схеме."
)

# Vision-readable uploads go to Claude as-is (it reads the table with its eyes).
_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def file_to_payload(content: bytes, filename: str):
    """Turn an uploaded file into either CSV-ish text (tabular/text) or a vision
    content block (pdf/image). Returns (text, vision_block) — exactly one is set."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""

    if ext in ("xlsx", "xls"):
        sheets = pd.read_excel(BytesIO(content), header=None, sheet_name=None)
        text = "\n\n".join(df.to_csv(index=False, header=False) for df in sheets.values())
        return text, None
    if ext == "csv":
        return content.decode("utf-8", errors="replace"), None
    if ext in ("txt", "tsv"):
        return content.decode("utf-8", errors="replace"), None
    if ext == "pdf":
        block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(content).decode()},
        }
        return None, block
    if ext in _IMAGE_TYPES:
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": _IMAGE_TYPES[ext], "data": base64.standard_b64encode(content).decode()},
        }
        return None, block
    # Unknown — try to decode as text and let the model do its best.
    return content.decode("utf-8", errors="replace"), None


def _chunk_lines(text: str, max_rows: int):
    """Split a big tabular dump into row-bounded chunks so each LLM call stays
    within the output-token budget. Keeps the first line (likely a header) on
    every chunk for column context."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= max_rows:
        return [text]
    header = lines[0]
    chunks = []
    for start in range(1, len(lines), max_rows):
        body = lines[start : start + max_rows]
        chunks.append("\n".join([header, *body]))
    return chunks


def _unit_code_reference():
    """Valid unit codes from the DB справочник (UN/ECE Rec 20). Source of truth —
    NOT a hardcoded dict. Returns (set_of_codes, guidance_string_for_the_prompt)."""
    from master_data.models import UnitOfMeasure

    rows = list(UnitOfMeasure.objects.filter(is_active=True).order_by("sort_order").values_list("code", "name"))
    valid = {code for code, _ in rows}
    guidance = ", ".join(f"{code}={name}" for code, name in rows)
    return valid, guidance


def _extract_one(client, model: str, system: str, *, text: str | None = None, vision_block=None) -> list[dict]:
    """One model call → raw item dicts. Resilient: a refusal, a truncated response,
    or unparseable JSON yields an empty list (logged) instead of raising, so one bad
    chunk never sinks a multi-chunk import. Genuine API/transport errors still raise
    for the caller to count."""
    user_content = []
    if vision_block is not None:
        user_content.append(vision_block)
        user_content.append({"type": "text", "text": "Извлеки позиции заявки из этого файла."})
    else:
        user_content.append({"type": "text", "text": f"Сырые данные из файла клиента:\n\n{text}"})

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        # Log token spend so this paid feature is observable in the import logs.
        logger.info("AI extract usage: input=%s output=%s", usage.input_tokens, usage.output_tokens)

    if response.stop_reason == "refusal":
        logger.warning("AI extract: model declined the request (%s)", getattr(response, "stop_details", None))
        return []
    if response.stop_reason == "max_tokens":
        # Output was cut off mid-JSON — likely unparseable below. Smaller chunks fix it.
        logger.warning("AI extract: hit max_tokens — output truncated; lower AI_IMPORT_CHUNK_ROWS")

    raw = next((b.text for b in response.content if b.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI extract: model JSON unparseable (len=%s) — skipping this chunk", len(raw or ""))
        return []
    return data.get("items", []) or []


def _normalize_items(items: list[dict], valid_codes: set) -> list[dict]:
    """Pure post-processing of the model's raw items → clean UBL-aligned rows.

    Coerces quantity to a positive int, validates unit_code against the DB справочник
    (off-list codes dropped to ''), truncates each field to its DB column limit, and
    drops rows identified by neither name nor mpn/gost. No I/O — unit-tested directly."""
    cleaned = []
    for raw_item in items:
        name = str(raw_item.get("name", "")).strip()
        mpn = str(raw_item.get("mpn", "")).strip()[:120]
        gost_drawing = str(raw_item.get("gost_drawing", "")).strip()[:120]
        # UBL: keep a line identified by name OR code; drop only fully-empty rows.
        if not (name or mpn or gost_drawing):
            continue
        try:
            quantity = max(1, int(float(raw_item.get("quantity") or 1)))
        except (ValueError, TypeError):
            quantity = 1
        unit_code = str(raw_item.get("unit_code", "")).strip().upper()
        if unit_code not in valid_codes:
            unit_code = ""
        cleaned.append(
            {
                "name": name,
                "quantity": quantity,
                "unit": str(raw_item.get("unit", "")).strip()[:32],
                "unit_code": unit_code,
                "mpn": mpn,
                "gost_drawing": gost_drawing,
                "note": str(raw_item.get("note", "")).strip(),
            }
        )
    return cleaned


def extract_request_items(content: bytes, filename: str) -> list[dict]:
    """Main entry: uploaded bytes → UBL-aligned request lines.

    Returns list of {name, quantity, unit, unit_code, mpn, gost_drawing, note}. Unit codes
    are validated against the DB справочник (UN/ECE Rec 20) — the model maps the
    client's free text to OUR codes, code only keeps valid ones. Chunks large
    files. Raises if AI import disabled / API errors — caller may fall back to the
    deterministic parser. A line with no name but an mpn/gost_drawing is KEPT (identified
    by code; the buyer completes it in the review grid).
    """
    if not settings.AI_IMPORT_ENABLED:
        raise RuntimeError("AI_IMPORT_DISABLED")

    # Guard against shipping a giant blob to the model: vision payloads (PDF/image)
    # are one base64 request, so an oversized file means a 413 + wasted spend. Bounded
    # by AI_IMPORT_MAX_BYTES; text is already row-bounded via chunking below.
    max_bytes = getattr(settings, "AI_IMPORT_MAX_BYTES", 10 * 1024 * 1024)
    if len(content) > max_bytes:
        raise RuntimeError(f"AI_IMPORT_FILE_TOO_LARGE ({len(content)} > {max_bytes} bytes)")

    model = settings.AI_IMPORT_MODEL
    import anthropic  # local import: the package is only required when AI import is enabled

    client = _client()
    valid_codes, code_guidance = _unit_code_reference()
    system = (
        SYSTEM_PROMPT
        + "\n\nКОДЫ ЕДИНИЦ ИЗМЕРЕНИЯ (UN/ECE Rec 20) — для поля unit_code выбери ОДИН код из "
        + "этого списка, наиболее подходящий по смыслу (или '' если не подходит ни один):\n"
        + code_guidance
    )
    text, vision_block = file_to_payload(content, filename)

    if vision_block is not None:
        # Single call — a transport error here propagates (nothing partial to keep).
        items = _extract_one(client, model, system, vision_block=vision_block)
    else:
        chunks = _chunk_lines(text, settings.AI_IMPORT_CHUNK_ROWS)
        items = []
        failures = 0
        for index, chunk in enumerate(chunks):
            try:
                chunk_items = _extract_one(client, model, system, text=chunk)
            except anthropic.APIError as exc:
                # Isolate a single failing chunk — keep what the others returned.
                failures += 1
                logger.warning("AI extract: chunk %s/%s failed (%s)", index + 1, len(chunks), exc)
                continue
            items.extend(chunk_items)
            logger.info(
                "AI extract: chunk %s/%s → %s items (total %s)", index + 1, len(chunks), len(chunk_items), len(items)
            )
        # Every chunk failed → surface a hard error so the caller falls back to the parser.
        if chunks and failures == len(chunks):
            raise RuntimeError("AI_EXTRACT_ALL_CHUNKS_FAILED")

    return _normalize_items(items, valid_codes)
