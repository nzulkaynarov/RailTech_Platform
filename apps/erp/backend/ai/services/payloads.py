"""Файл клиента → содержимое сообщения `user` для шлюза (OpenAI-совместимый формат LiteLLM).

Таблицы и текст едут текстом (CSV-подобный дамп), PDF и изображения — блоками `file` /
`image_url` с data-URL base64: LiteLLM переводит их в документ/изображение провайдера. Сам
файл — данные пользователя: он всегда в сообщении `user`, никогда в системном промпте.
"""

from __future__ import annotations

import base64
from io import BytesIO

import pandas as pd

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
#: Потолок строк на лист Excel (аудит L4): маленький xlsx-«зип-бомба» иначе раздуется в DataFrame.
MAX_SHEET_ROWS = 50_000


def _extension(filename: str) -> str:
    name = filename or ""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _data_url(media_type: str, content: bytes) -> str:
    return f"data:{media_type};base64,{base64.standard_b64encode(content).decode()}"


def file_to_payload(content: bytes, filename: str) -> tuple[str | None, dict | None]:
    """(текст, vision-блок) — ровно одно из двух задано.

    xlsx/xls → CSV всех листов; csv/txt/tsv и неизвестное → декодированный текст;
    pdf → блок `file`; png/jpg/webp/gif → блок `image_url`.
    """
    ext = _extension(filename)
    if ext in ("xlsx", "xls"):
        sheets = pd.read_excel(BytesIO(content), header=None, sheet_name=None, nrows=MAX_SHEET_ROWS)
        return "\n\n".join(df.to_csv(index=False, header=False) for df in sheets.values()), None
    if ext == "pdf":
        block = {
            "type": "file",
            "file": {"filename": filename or "document.pdf", "file_data": _data_url("application/pdf", content)},
        }
        return None, block
    if ext in IMAGE_TYPES:
        return None, {"type": "image_url", "image_url": {"url": _data_url(IMAGE_TYPES[ext], content)}}
    # csv / txt / tsv / неизвестное — текстом, модель разберётся.
    return content.decode("utf-8", errors="replace"), None


def chunk_lines(text: str, max_rows: int) -> list[str]:
    """Большой табличный дамп → куски по `max_rows` строк; первая строка (шапка) — в каждом куске."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= max_rows:
        return [text]
    header = lines[0]
    return ["\n".join([header, *lines[start : start + max_rows]]) for start in range(1, len(lines), max_rows)]
