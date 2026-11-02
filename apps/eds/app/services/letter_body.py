"""Тело письма на бланке (P4): нормализация и проверка по контракту `documents/body.schema.json` (`rt_docs`, без pango)
и плоский текст для поиска (`documents.text` остаётся производным от тела, D-DOC2)."""

from typing import Any, Final

from rt_docs import BodyError, normalize_body, validate_body

from app.errors import invalid_fields
from app.schemas.documents import DocumentBody

TEXT_LIMIT: Final = 20000
_BLOCKS: Final = {"paragraph", "heading", "listItem", "tableRow", "signature", "block"}


def clean(body: DocumentBody) -> dict[str, Any]:
    """Тело для хранения: без управляющих символов, по схеме и лимитам (глубина, размер); иначе 422 `body`."""
    try:
        normalized = normalize_body(body.raw())
        validate_body(normalized)
    except BodyError as exc:
        raise invalid_fields("Текст письма не прошёл проверку бланка.", body=str(exc)[:300]) from None
    return normalized


def _walk(node: Any, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    kind = node.get("type")
    if kind in ("tableCell", "tableHeader"):  # ячейка — одна строка, ячейки строки — через пробел
        cell: list[str] = []
        for child in node.get("content") or []:
            _walk(child, cell)
        out.append(" ".join("".join(cell).split()) + "\t")
        return
    if kind == "text" and isinstance(node.get("text"), str):
        out.append(node["text"])
    elif kind == "hardBreak":
        out.append("\n")
    for child in node.get("content") or []:
        _walk(child, out)
    if kind in _BLOCKS:
        out.append("\n")


def plain_text(body: dict[str, Any]) -> str:
    """Текст тела по абзацам (ячейки таблицы — через табуляцию) — для поиска и `text`; пусто — «—»."""
    parts: list[str] = []
    _walk(body.get("doc"), parts)
    lines = [" ".join(line.split("\t")).strip() for line in "".join(parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    return (text or "—")[:TEXT_LIMIT]
