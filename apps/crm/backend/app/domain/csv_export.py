"""CSV для Excel с русской локалью (аудит 2026-10-12 §5 «Экспорт»). Чистые функции.

Формат выбран под Excel в ru-локали, где им открывают файл двойным щелчком:
- UTF-8 с BOM — иначе Excel читает кириллицу как cp1251 и показывает «кракозябры»;
- разделитель `;` — в ru-локали запятая — десятичный разделитель, и Excel ждёт `;`;
- дробные числа с запятой, даты — `ДД.ММ.ГГГГ ЧЧ:ММ` по Ташкенту (CLAUDE.md §11);
- ячейки, начинающиеся с `= + - @`, экранируются апострофом (защита от CSV-инъекции формул).
"""

import csv
import io
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

BOM: Final = "﻿"
DELIMITER: Final = ";"
TASHKENT: Final = ZoneInfo("Asia/Tashkent")
_FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")

Cell = str | int | float | Decimal | bool | date | datetime | Sequence[str] | None


def format_cell(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, datetime):
        return value.astimezone(TASHKENT).strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, Decimal | float):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, int):
        return str(value)
    text = value if isinstance(value, str) else ", ".join(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def render(headers: Sequence[str], rows: Iterable[Sequence[Cell]]) -> Iterator[str]:
    """Строки CSV по одной: первая — BOM и заголовки; переводы строк — CRLF (как у Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator="\r\n")

    def line(cells: Sequence[str]) -> str:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(cells)
        return buffer.getvalue()

    yield BOM + line(list(headers))
    for row in rows:
        yield line([format_cell(cell) for cell in row])
