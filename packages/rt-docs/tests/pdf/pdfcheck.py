"""Разбор PDF для эталонных тестов (pypdf): страницы, текст, размер, шрифты, нижняя строка текста над подвалом.

Тесты не сравнивают байты PDF: только число страниц, заполненность последней и текст — то, что видит человек.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from pypdf import PdfReader

MM = 72 / 25.4


@dataclass(frozen=True)
class Page:
    text: str
    width: float
    height: float
    lowest_text_y: float  # базовая линия самой нижней строки потока (выше нижнего поля), pt от низа листа


def pages(pdf: bytes, *, bottom_margin_mm: float = 20) -> list[Page]:
    out = []
    for page in PdfReader(BytesIO(pdf)).pages:
        ys: list[float] = []

        def visit(text: str, cm: list[float], tm: list[float], _font: Any, _size: Any, ys: list[float] = ys) -> None:
            if text.strip():
                ys.append(tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

        text = page.extract_text(visitor_text=visit)
        floor = bottom_margin_mm * MM
        flow = [y for y in ys if y > floor]
        box = page.mediabox
        out.append(
            Page(text=text, width=float(box.width), height=float(box.height), lowest_text_y=min(flow) if flow else 0)
        )
    return out


def pdf_fill(page: Page, *, top_mm: float = 20, bottom_mm: float = 20) -> float:
    """Заполненность страницы по PDF: от верхнего поля до базовой линии нижней строки (без нижнего выноса букв)."""
    top = page.height - top_mm * MM
    height = page.height - (top_mm + bottom_mm) * MM
    return (top - page.lowest_text_y) / height


def fonts(pdf: bytes) -> set[str]:
    names: set[str] = set()
    for page in PdfReader(BytesIO(pdf)).pages:
        resources: Any = page["/Resources"]
        for font in (resources.get("/Font") or {}).values():
            names.add(str(font.get_object()["/BaseFont"]))
    return names
