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
        "name_canonical": {
            "type": "string",
            "description": (
                "Каноническое РУССКОЕ наименование этой же позиции для поиска по каталогу: "
                "транслитерируй латиницу в кириллицу и приведи к словарной форме на русском "
                "(напр. 'tormoznaya koloda' → 'Тормозная колодка', 'avtoscepka SA-3' → "
                "'Автосцепка СА-3'). Бренды/модели/коды оставляй как есть. Если name уже на "
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
    "6. Языки могут быть любыми (рус./узб./англ.). Поле name оставляй как в оригинале, "
    "а в name_canonical верни каноническое РУССКОЕ наименование той же позиции "
    "(транслитерация латиницы в кириллицу + словарная форма) для поиска по каталогу — "
    "бренды, модели и коды при этом не переводи.\n"
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
        # nrows cap per sheet (audit L4) — a small zip-bomb-style xlsx can otherwise expand to
        # a huge in-memory DataFrame and OOM the worker (deterministic paths cap at 50_000 too).
        sheets = pd.read_excel(BytesIO(content), header=None, sheet_name=None, nrows=50_000)
        text = "\n\n".join(df.to_csv(index=False, header=False) for df in sheets.values())
        return text, None
    if ext == "csv":
        return content.decode("utf-8", errors="replace"), None
    if ext in ("txt", "tsv"):
        return content.decode("utf-8", errors="replace"), None
    if ext == "pdf":
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(content).decode(),
            },
        }
        return None, block
    if ext in _IMAGE_TYPES:
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _IMAGE_TYPES[ext],
                "data": base64.standard_b64encode(content).decode(),
            },
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
        # Каноническое русское имя для поиска по каталогу; падаем обратно на name,
        # если модель его не вернула (старый стаб/пустой ответ).
        name_canonical = str(raw_item.get("name_canonical", "")).strip()[:500] or name[:500]
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
                "name_canonical": name_canonical,
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

    Returns list of {name, name_canonical, quantity, unit, unit_code, mpn, gost_drawing, note}.
    `name_canonical` is the canonical Russian search name (Latin↔Cyrillic normalised) — the
    original `name` is preserved verbatim for display. Unit codes
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


# ── Semantic matching: заявка line → catalog.Product (roadmap #1) ──────────
# Cheap SQL trigram preselect narrows the catalog to a shortlist per line; Claude
# only RANKS that shortlist (product_id MUST come from the DB candidates — Rule 1,
# the model never invents an id). Multilingual (рус/узб/англ) ranking is the win:
# a free-text заявка line maps to a differently-named catalog product.
MATCH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_index": {"type": "integer"},
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "confidence": {"type": "number", "description": "0..1"},
                                "reason": {"type": "string"},
                            },
                            "required": ["product_id", "confidence", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["line_index", "candidates"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}

MATCH_SYSTEM_PROMPT = (
    "Ты сопоставляешь строки заявки на закупку с товарами каталога B2B-площадки "
    "(железнодорожное и промышленное оборудование). Для каждой строки заявки даны "
    "КАНДИДАТЫ из базы (каждый с id). Верни для каждой строки список подходящих "
    "product_id, РАНЖИРОВАННЫХ по релевантности, с confidence (0..1) и кратким reason.\n\n"
    "ПРАВИЛА:\n"
    "1. product_id ВЫБИРАЙ ТОЛЬКО из предложенных кандидатов этой строки. НЕ выдумывай id.\n"
    "2. Если ни один кандидат не подходит — верни пустой список candidates для строки.\n"
    "3. Совпадение по артикулу/ГОСТ/чертежу — сильный сигнал (высокий confidence).\n"
    "4. Языки могут различаться (рус/узб/англ) — сопоставляй по смыслу, не по буквам.\n"
    "5. Не присваивай высокий confidence наугад: уверенный неверный мэтч хуже пустого.\n"
    "Верни результат строго по JSON-схеме."
)


def _shortlist_products(line: dict, domain_code: str | None, limit: int = 8):
    """Trigram + exact-code preselect of catalog Products for one заявка line.

    Bilingual: the line's raw `name` AND its canonical Russian `name_canonical`
    (Latin↔Cyrillic normalised by the AI parser) are BOTH fed to trigram similarity,
    and we keep the GREATEST score. This is what lets a Latin query like
    «tormoznaya koloda» preselect a Cyrillic catalog row («Тормозная колодка»):
    the raw name trigram-misses the кириллица, but name_canonical hits it.
    """
    from django.contrib.postgres.search import TrigramSimilarity
    from django.db.models.functions import Greatest

    from catalog.models import Product

    # PUBLISHED only — the AI match must not surface competitors' DRAFT/ARCHIVED cards that
    # the catalog list endpoint deliberately hides (review 2026-06-25, HIGH #3).
    qs = Product.objects.filter(status__code="PUBLISHED")
    if domain_code:
        qs = qs.filter(domain_type__code=domain_code)

    found: dict[int, object] = {}
    gost = (line.get("gost_drawing") or "").strip()
    if gost:
        for product in qs.filter(gost_drawing__iexact=gost)[:limit]:
            found[product.id] = product

    # Search terms: the raw name AND the canonical Russian form. Deduped so a single
    # term (or when canonical == name) doesn't waste a redundant similarity column.
    name = (line.get("name") or "").strip()
    name_canonical = (line.get("name_canonical") or "").strip()
    terms = [term for term in dict.fromkeys([name, name_canonical]) if term]
    if terms and len(found) < limit:
        similarities = [TrigramSimilarity("name", term) for term in terms]
        # GREATEST across terms — a hit on either the raw or canonical name counts.
        similarity = similarities[0] if len(similarities) == 1 else Greatest(*similarities)
        ranked = qs.annotate(similarity=similarity).filter(similarity__gt=0.1).order_by("-similarity")[:limit]
        for product in ranked:
            found.setdefault(product.id, product)
    return list(found.values())[:limit]


def match_lines_to_catalog(lines: list[dict], domain_code: str | None = None, top_k: int = 3) -> list[dict]:
    """Map each заявка line to up to `top_k` catalog Product candidates.

    Returns [{line_index, name_canonical, candidates: [{product_id, name, sku, confidence,
    reason}]}] only for lines that have at least one valid candidate. `name_canonical` is
    echoed back so the caller can persist it on the QuoteItem alongside the chosen product.
    Empty list if AI disabled. The buyer/seller confirms a candidate in the grid
    (human-in-loop, never auto-binds).
    """
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not lines:
        return []

    shortlists: dict[int, dict] = {}
    prompt_blocks: list[str] = []
    for idx, line in enumerate(lines):
        products = _shortlist_products(line, domain_code)
        if not products:
            continue
        shortlists[idx] = {p.id: p for p in products}
        cand = "; ".join(
            f"[id={p.id}] {p.name}"
            + (f" (ГОСТ {p.gost_drawing})" if getattr(p, "gost_drawing", "") else "")
            + (f" [SKU {p.sku}]" if getattr(p, "sku", "") else "")
            for p in products
        )
        label = (line.get("name") or "").strip()
        canonical = (line.get("name_canonical") or "").strip()
        if canonical and canonical.casefold() != label.casefold():
            label += f" | рус. {canonical}"
        if line.get("mpn"):
            label += f" | артикул {line['mpn']}"
        if line.get("gost_drawing"):
            label += f" | ГОСТ {line['gost_drawing']}"
        prompt_blocks.append(f"Строка {idx}: {label or '(без названия)'}\n  Кандидаты: {cand}")

    if not prompt_blocks:
        return []

    client = _client()
    user_msg = "Сопоставь строки заявки с кандидатами каталога:\n\n" + "\n\n".join(prompt_blocks)
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=3000,
        system=MATCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        output_config={"format": {"type": "json_schema", "schema": MATCH_RESULT_SCHEMA}},
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info(
            "AI match usage: input=%s output=%s lines=%s", usage.input_tokens, usage.output_tokens, len(prompt_blocks)
        )
    if response.stop_reason == "refusal":
        logger.warning("AI match: model declined (%s)", getattr(response, "stop_details", None))
        return []

    raw = next((b.text for b in response.content if b.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI match: unparseable JSON (len=%s)", len(raw or ""))
        return []

    result: list[dict] = []
    for match in data.get("matches", []):
        idx = match.get("line_index")
        pool = shortlists.get(idx)
        if not pool:
            continue
        valid = []
        for cand in match.get("candidates", []):
            product = pool.get(cand.get("product_id"))
            if product is None:  # Rule 1: id must be from the DB shortlist
                continue
            valid.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "sku": getattr(product, "sku", "") or "",
                    "confidence": round(float(cand.get("confidence") or 0), 3),
                    "reason": (cand.get("reason") or "")[:300],
                }
            )
        valid.sort(key=lambda c: -c["confidence"])
        if valid:
            # Echo the canonical Russian name so callers can persist it on QuoteItem.
            source_line = lines[idx] if 0 <= idx < len(lines) else {}
            name_canonical = (source_line.get("name_canonical") or "").strip()
            result.append({"line_index": idx, "name_canonical": name_canonical, "candidates": valid[:top_k]})
    return result
