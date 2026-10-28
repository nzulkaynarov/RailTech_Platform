"""Входные данные рендера: бланк, реквизиты документа, значения переменных, параметры страницы.

Бланк и реквизиты — данные вызывающего (ERP — владелец бланка, EDS — проекция; ADR-0020 п. 5), пакет в базы не ходит.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from .errors import LetterheadError

Lang = Literal["ru", "uz", "en"]
LANGS: tuple[Lang, ...] = ("ru", "uz", "en")


class Layout(StrEnum):
    """Макет бланка по виду документа (variables.yaml → kinds.*.layout)."""

    LETTER = (
        "letter"  # письмо: шапка бланка на первой странице, реквизиты письма, адресат, «Исполнитель» внизу последней
    )
    INTERNAL = "internal"  # служебка, заявление, отчёт: без логотипа, компактная шапка
    COMMERCIAL = "commercial"  # КП, договор, счёт, акт: шапка бланка, регистрационный подвал на каждой странице


class Density(StrEnum):
    COMPACT = "compact"
    NORMAL = "normal"
    SPACIOUS = "spacious"


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})
LOGO_MAX_BYTES = 512 * 1024


@dataclass(frozen=True)
class Logo:
    """Логотип бланка байтами: рендер не читает файлы и не ходит в сеть (безопасный fetcher)."""

    data: bytes
    mime: str

    def __post_init__(self) -> None:
        if self.mime not in LOGO_MIME:
            raise LetterheadError(f"logo mime {self.mime!r} is not allowed (png, jpeg, webp)")
        if not self.data or len(self.data) > LOGO_MAX_BYTES:
            raise LetterheadError("logo must be 1 byte … 512 KiB")


@dataclass(frozen=True)
class Letterhead:
    """Бланк компании: имя, строки реквизитов, подвал, логотип, акцентный цвет и семейство шрифта.

    Цвет и шрифт документа — только отсюда, не из тела (ADR-0020 п. 2).
    """

    company_name: str
    requisites: Sequence[str] = ()  # строки под названием: адрес, ИНН, банк, телефон, почта
    footer: Sequence[str] = ()  # регистрационный подвал коммерческого макета (каждая страница)
    logo: Logo | None = None
    accent: str = "#15294d"
    font: Literal["sans", "serif"] = "sans"

    def __post_init__(self) -> None:
        if not _HEX.match(self.accent):
            raise LetterheadError(f"accent {self.accent!r} must be #rrggbb")
        if self.font not in ("sans", "serif"):
            raise LetterheadError("font must be sans or serif")


@dataclass(frozen=True)
class DocumentMeta:
    """Реквизиты документа вне тела: заголовок, номер, дата, адресат и «на №» письма, исполнитель."""

    title: str | None = None
    number: str | None = None
    date: date | None = None
    addressee: Sequence[str] = ()
    reply_to: str | None = None
    executor: str | None = None


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "UZS"


Value = str | int | Decimal | date | Money


@dataclass(frozen=True)
class Tuning:
    """Подстройка вёрстки («Подогнать»): плотность, межстрочный, поля и отступ до текста — в пределах схемы тела."""

    density: Density | None = None
    line_height: float | None = None  # 1.2 … 1.6
    margin_delta_mm: int = 0  # −6 … 0: поля сверху и снизу уже
    lead_mm: int = 0  # 0 … 30: отступ до текста короткого письма

    def __post_init__(self) -> None:
        if self.line_height is not None and not 1.2 <= self.line_height <= 1.6:
            raise ValueError("line_height must be within 1.2 … 1.6")
        if not -6 <= self.margin_delta_mm <= 0:
            raise ValueError("margin_delta_mm must be within −6 … 0")
        if not 0 <= self.lead_mm <= 30:
            raise ValueError("lead_mm must be within 0 … 30")

    def to_json(self) -> dict[str, float | int]:
        """Для `page.tuning` тела (density хранится отдельно — `page.density`)."""
        out: dict[str, float | int] = {}
        if self.line_height is not None:
            out["lineHeight"] = self.line_height
        if self.margin_delta_mm:
            out["marginDeltaMm"] = self.margin_delta_mm
        if self.lead_mm:
            out["leadMm"] = self.lead_mm
        return out


@dataclass(frozen=True)
class PageStats:
    """Статистика страниц: число и заполненность последней (доля высоты области текста, 0 … 1)."""

    pages: int
    last_page_fill: float


@dataclass(frozen=True)
class RenderResult:
    pdf: bytes
    stats: PageStats
    tuning: Tuning
    warnings: tuple[str, ...] = ()
    blocked_urls: tuple[str, ...] = field(default=())
