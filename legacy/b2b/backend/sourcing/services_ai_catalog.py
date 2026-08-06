"""R5b — экстракция строк прайс-листа каталога из ЛЮБОГО файла (Excel/PDF/фото).

Владелец: «нет массовой загрузки товаров с помощью ИИ, хотя у нас уже есть такой
функционал». Этот модуль ПЕРЕИСПОЛЬЗУЕТ проверенный vision-механизм заявок
(`services_ai.file_to_payload` → base64 `document`/`image` block, `_client()`), но целится
в схему КАТАЛОЖНОГО импорта: ключи каждой строки = РУССКИЕ заголовки шаблона
(`CATALOG_TEMPLATE_HEADERS`), поэтому DataFrame из этих строк проходит через штатный
разбор шапки (`catalog_import._resolve_columns`) без единой новой ветки.

Порядок путей принципиален (PRODUCT RULE: трение не добавляем, токены не жжём зря):
  1. БЕСПЛАТНЫЙ путь — .xlsx, в котором штатный разбор находит колонку «Наименование»
     (наш шаблон или совместимый прайс), разбирается pandas'ом напрямую, БЕЗ вызова ИИ.
  2. ИИ-путь — всё остальное (PDF/скан/фото/чужой xlsx): Claude ДОСЛОВНО переносит строки
     документа в схему шаблона (structured output, максимум MAX_AI_PRICE_ROWS строк).

Пустой ответ / refusal / непарсибельный JSON → пустой список (нейтрально, как enrich).
Выключенный ИИ или превышение байтового потолка на ИИ-пути — RuntimeError, как у
`extract_request_items` (вызывается ТОЛЬКО с Celery — ARCH-01, никогда из request path).
"""

from __future__ import annotations

import json
import logging
import zipfile
from io import BytesIO

import pandas as pd
from django.conf import settings

from .catalog_import import MAX_EXCEL_ROWS, _resolve_columns
from .services_ai import _client, file_to_payload
from .views_templates import CATALOG_TEMPLATE_HEADERS

logger = logging.getLogger(__name__)

#: Потолок строк, которые просим у модели за один документ (жёстко закреплён и в промпте).
MAX_AI_PRICE_ROWS = 500
#: Предел длины одной ячейки — дальше это уже не значение поля карточки, а мусор распознавания.
MAX_CELL_CHARS = 500

# Structured Outputs: свойства строки = РУССКИЕ заголовки шаблона (см. модульный докстринг).
# Все обязательны ('' если нет — additionalProperties=false запрещает опциональные).
_ROW_FIELD_HINTS = {
    "Наименование": "Название товара/позиции ДОСЛОВНО как в документе. '' если строка не товар.",
    "Бренд": "Производитель/бренд как напечатан. '' если не указан.",
    "Артикул производителя": "Артикул/каталожный номер производителя (MPN). '' если нет.",
    "ГОСТ / Чертёж": "Номер ГОСТ или чертежа (напр. 'ГОСТ 1234-89'). '' если нет.",
    "Артикул поставщика": "Внутренний артикул/код продавца. '' если нет.",
    "Описание": "Описание/характеристики позиции. '' если нет.",
    "Категория": "Категория/раздел, как напечатан в документе. '' если нет.",
    "Код ТН ВЭД": "Код ТН ВЭД только цифрами. '' если нет.",
    "Направление": "Направление/домен товара, как напечатано. '' если нет.",
    "Ед. изм.": "Единица измерения (шт, кг, м …). '' если нет.",
    "Цена": "Цена ЧИСЛОМ-строкой без пробелов и валютных знаков, точка как разделитель "
    "(напр. '150.50'). '' если цены нет.",
    "Валюта": "Код валюты ISO 4217 (UZS, USD, EUR, RUB), если валюта напечатана или однозначна "
    "по символу (сум→UZS, $→USD). '' если не указана.",
    "Наличие": "Наличие/склад как напечатано. '' если нет.",
    "Срок поставки": "Срок поставки как напечатан. '' если нет.",
    "Мин. заказ": "Минимальный заказ числом-строкой. '' если нет.",
}
PRICE_ROW_SCHEMA = {
    "type": "object",
    "properties": {header: {"type": "string", "description": _ROW_FIELD_HINTS[header]} for header in _ROW_FIELD_HINTS},
    "required": list(_ROW_FIELD_HINTS),
    "additionalProperties": False,
}
PRICE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {"rows": {"type": "array", "items": PRICE_ROW_SCHEMA}},
    "required": ["rows"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Ты — парсер прайс-листов для каталога B2B-площадки (железнодорожное и промышленное "
    "оборудование, материалы, услуги). На вход поступает прайс-лист продавца: таблица, PDF "
    "или скан/фото. Твоя задача — переписать строки товаров в заданную схему.\n\n"
    "ПРАВИЛА:\n"
    "1. Переноси значения ДОСЛОВНО из документа. НИЧЕГО НЕ ВЫДУМЫВАЙ и не вычисляй: "
    "если поля нет в документе — верни пустую строку ''. НЕ добавляй товары, которых нет.\n"
    "2. Цена и минимальный заказ — числом-строкой без пробелов и валютных знаков, "
    "десятичный разделитель — точка ('1 234 567,89 сум' → '1234567.89').\n"
    "3. Валюта — кодом ISO 4217 (UZS, USD, EUR, RUB), только если она напечатана в документе "
    "или однозначна по символу (сум/сўм → UZS, $ → USD, € → EUR, ₽ → RUB); иначе ''.\n"
    "4. ИГНОРИРУЙ заголовки таблицы, шапку документа, нумерацию, итоги, пустые и служебные "
    "строки.\n"
    f"5. Верни НЕ БОЛЕЕ {MAX_AI_PRICE_ROWS} строк — первые по порядку документа.\n"
    "Верни результат строго по JSON-схеме."
)


def _rows_from_template_xlsx(file_bytes: bytes) -> list[dict] | None:
    """Бесплатный путь: .xlsx, чью шапку понимает штатный разбор → строки без единого токена.

    None означает «это не наш формат» (шапка не распозналась или файл не читается как Excel) —
    вызывающий уходит на ИИ-путь. Ключи строк здесь — ОРИГИНАЛЬНЫЕ заголовки файла: раз шапка
    уже распозналась, `run_catalog_import_frame` разберёт их ровно как штатный импорт.
    """
    try:
        data_frame = pd.read_excel(BytesIO(file_bytes), nrows=MAX_EXCEL_ROWS, dtype=str)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile):
        return None
    columns = _resolve_columns([str(column).lower().strip() for column in data_frame.columns])
    if not columns["name"]:
        return None
    return data_frame.to_dict(orient="records")


def _normalize_ai_rows(raw_rows: list) -> list[dict]:
    """Сырые строки модели → чистые словари схемы шаблона (только известные ключи, всё строками)."""
    cleaned = []
    for raw_row in raw_rows[:MAX_AI_PRICE_ROWS]:
        if not isinstance(raw_row, dict):
            continue
        row = {header: str(raw_row.get(header) or "").strip()[:MAX_CELL_CHARS] for header in CATALOG_TEMPLATE_HEADERS}
        if any(row.values()):
            cleaned.append(row)
    return cleaned


def extract_price_rows(file_bytes: bytes, filename: str) -> tuple[list[dict], bool]:
    """Байты прайс-листа → (строки для `run_catalog_import_frame`, использовался ли ИИ).

    Второй элемент кортежа честно говорит, был ли платный вызов: бесплатный xlsx-путь
    возвращает False, и обработчик фичи отражает это в отчёте (`ai_used`). Пустой список —
    нейтральный исход ИИ-пути (refusal / пустой ответ / непарсибельный JSON). Raises
    RuntimeError("AI_IMPORT_DISABLED" / "AI_IMPORT_FILE_TOO_LARGE") на ИИ-пути — как
    `extract_request_items`, чтобы вызывающий мог показать стабильный код ошибки.
    """
    extension = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if extension == "xlsx":
        template_rows = _rows_from_template_xlsx(file_bytes)
        if template_rows is not None:
            return template_rows, False

    if not getattr(settings, "AI_IMPORT_ENABLED", False):
        raise RuntimeError("AI_IMPORT_DISABLED")
    max_bytes = getattr(settings, "AI_IMPORT_MAX_BYTES", 10 * 1024 * 1024)
    if len(file_bytes) > max_bytes:
        raise RuntimeError(f"AI_IMPORT_FILE_TOO_LARGE ({len(file_bytes)} > {max_bytes} bytes)")

    # PDF/изображения едут в модель тем же vision-способом, что у заявок; xlsx с нераспознанной
    # шапкой приезжает сюда CSV-текстом (file_to_payload сам решает, что чем подавать).
    text, vision_block = file_to_payload(file_bytes, filename)
    user_content: list[dict] = []
    if vision_block is not None:
        user_content.append(vision_block)
        user_content.append({"type": "text", "text": "Извлеки строки прайс-листа из этого документа."})
    else:
        user_content.append({"type": "text", "text": f"Сырые данные прайс-листа продавца:\n\n{text}"})

    response = _client().messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": PRICE_RESULT_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info("AI price-extract usage: input=%s output=%s", usage.input_tokens, usage.output_tokens)
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("AI price-extract: model declined (%s)", getattr(response, "stop_details", None))
        return [], True
    if getattr(response, "stop_reason", None) == "max_tokens":
        # Вывод оборван посреди JSON — ниже он, скорее всего, не разберётся (нейтральный исход).
        logger.warning("AI price-extract: hit max_tokens — output truncated")

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI price-extract: unparseable JSON (len=%s)", len(raw or ""))
        return [], True
    return _normalize_ai_rows(data.get("rows") or []), True
