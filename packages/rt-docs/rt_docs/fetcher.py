"""Безопасный доступ к ресурсам при рендере: белый список вместо сети и файловой системы (ADR-0020 п. 3).

WeasyPrint по умолчанию открывает любые `http(s)://`, `file://`, `ftp://` из документа (SSRF и чтение файлов сервера;
CVE-2025-68616 — повод нового `URLFetcher` в 68.0). Здесь разрешено только:
- `rtdocs:fonts/<файл>` — вшитые шрифты пакета (точные имена, без путей);
- `rtdocs:logo` — логотип бланка, переданный байтами в `Letterhead.logo`;
- `data:image/(png|jpeg|gif|webp);base64,…` — встроенная растровая картинка, тип сверяется с сигнатурой байтов (SVG и
  всё, что выдаёт себя за картинку, запрещены: в SVG бывает скрипт). Логотип бланка проверяется так же (`Logo`).
Всё остальное отклоняется и попадает в `blocked` (результат рендера → `RenderResult.blocked_urls`).
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from importlib import resources

from .css import FONT_FILES
from .model import Logo, image_mime

FONT_NAMES = frozenset(name for files in FONT_FILES.values() for name, _, _ in files)
_DATA_IMAGE = re.compile(r"^data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)
MAX_DATA_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Resource:
    data: bytes
    mime: str


@dataclass
class ResourcePolicy:
    """Решает, что отдать рендеру по адресу; всё неразрешённое — None и запись в `blocked`."""

    logo: Logo | None = None
    blocked: list[str] = field(default_factory=list)

    def resolve(self, url: str) -> Resource | None:
        if url.startswith("rtdocs:fonts/"):
            name = url.removeprefix("rtdocs:fonts/")
            if name in FONT_NAMES:
                return Resource(font_bytes(name), "font/ttf")
        elif url == "rtdocs:logo" and self.logo is not None:
            return Resource(self.logo.data, self.logo.mime)
        elif match := _DATA_IMAGE.match(url):
            try:
                data = base64.b64decode(match[2], validate=False)
            except (binascii.Error, ValueError):
                data = b""
            if 0 < len(data) <= MAX_DATA_BYTES and image_mime(data) == match[1].lower():
                return Resource(data, match[1].lower())
        self.blocked.append(url if len(url) <= 200 else url[:200] + "…")
        return None


def font_bytes(name: str) -> bytes:
    if name not in FONT_NAMES:
        raise KeyError(name)
    return resources.files("rt_docs").joinpath("fonts", name).read_bytes()
