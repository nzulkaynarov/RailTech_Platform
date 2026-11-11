"""Справочники файлом (решение владельца 2026-11-11).

Исследование — `docs/research/2026-11-11-reference-data/README.md` §C1. Шаблон — это выгрузка самого
списка: `code`, `name_ru`, `name_uz`, `name_en`, `active`, затем поля вида. Загрузка сначала
проверяется без записи (что добавится, изменится, не изменится, где ошибка), применяются ровно
проверенные строки через обычные действия домена. Ключ — код: есть и найден — строка меняется;
пусто — создаётся (код даёт домен из названия). Пустая ячейка у существующей строки значение не
меняет. Удалять файлом нельзя: строк, которых нет в файле, загрузка не касается. xlsx читает и пишет
openpyxl, csv — стандартная библиотека.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from typing import Any, Literal

from openpyxl import Workbook, load_workbook

from app.schemas_dictionaries import AttrValue, Dictionary, DictionaryAttr, DictionaryItem

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 2000
BASE_COLUMNS = ("code", "name_ru", "name_uz", "name_en", "active")
_TRUE = {"1", "true", "yes", "y", "да", "д", "ha", "+", "x"}
_FALSE = {"0", "false", "no", "n", "нет", "н", "yo'q", "yoʻq", "yo‘q", "-"}

Action = Literal["add", "update", "unchanged", "error"]


class FileProblemError(Exception):
    """Файл целиком не читается: формат, размер, шапка."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class RowPlan:
    line: int
    code: str | None
    name: str
    action: Action
    fields: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    create: dict[str, Any] | None = None
    patch: dict[str, Any] | None = None


# --- выгрузка ------------------------------------------------------------------------------------


def columns(dictionary: Dictionary) -> list[str]:
    return [*BASE_COLUMNS, *(a.key for a in dictionary.attrs)]


def _cell(value: AttrValue) -> str | int | bool:
    if value is None:
        return ""
    return value


def export(
    dictionary: Dictionary, items: list[DictionaryItem], fmt: Literal["xlsx", "csv"]
) -> bytes:
    header = columns(dictionary)
    rows: list[list[str | int | bool]] = [
        [
            item.code,
            item.name.ru,
            item.name.uz,
            item.name.en,
            "да" if item.active else "нет",
            *(_cell(item.attrs.get(a.key)) for a in dictionary.attrs),
        ]
        for item in items
    ]
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
        return ("﻿" + out.getvalue()).encode("utf-8")  # BOM: Excel открывает кириллицу верно
    book = Workbook()
    sheet = book.create_sheet(dictionary.kind[:31], 0)
    del book[book.sheetnames[1]]  # пустой лист по умолчанию
    sheet.title = dictionary.kind[:31]
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# --- разбор файла --------------------------------------------------------------------------------


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read(raw: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Шапка и строки `(номер строки файла, {столбец: текст})`; пустые строки пропускаются."""
    if not raw:
        raise FileProblemError("empty_file")
    if len(raw) > MAX_FILE_BYTES:
        raise FileProblemError("file_too_large")
    table: list[list[str]]
    if raw[:2] == b"PK":
        try:
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
            raise FileProblemError("unreadable_file") from exc
        sheet = book.worksheets[0]
        table = [[_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        book.close()
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise FileProblemError("not_utf8") from exc
        sample = text[:4096]
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        table = [
            [c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        ]
    table = [row for row in table if any(cell for cell in row)]
    if not table:
        raise FileProblemError("empty_file")
    header = [cell.strip().lower() for cell in table[0]]
    body = table[1:]
    if len(body) > MAX_ROWS:
        raise FileProblemError("too_many_rows", str(MAX_ROWS))
    rows = [
        (
            index + 2,
            {name: (row[i] if i < len(row) else "") for i, name in enumerate(header) if name},
        )
        for index, row in enumerate(body)
    ]
    return header, rows


# --- проверка строк ------------------------------------------------------------------------------


def _flag(text: str) -> bool | None:
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(value)


def _attr(attr: DictionaryAttr, text: str) -> AttrValue:
    if attr.type == "boolean":
        return _flag(text)
    if attr.type == "integer":
        number = int(text)
        if (attr.minimum is not None and number < attr.minimum) or (
            attr.maximum is not None and number > attr.maximum
        ):
            raise ValueError(text)
        return number
    if attr.options is not None and text not in {o.value for o in attr.options}:
        raise ValueError(text)
    return text


def plan(
    dictionary: Dictionary,
    items: list[DictionaryItem],
    header: list[str],
    rows: list[tuple[int, dict[str, str]]],
) -> list[RowPlan]:
    missing = [c for c in ("code", "name_ru") if c not in header]
    if missing:
        raise FileProblemError("missing_columns", ", ".join(missing))
    known = set(columns(dictionary))
    extra = [c for c in header if c and c not in known]
    if extra:
        raise FileProblemError("unknown_columns", ", ".join(extra))
    existing = {item.code: item for item in items}
    attrs = {a.key: a for a in dictionary.attrs}
    seen: set[str] = set()
    plans: list[RowPlan] = []
    for line, row in rows:
        code = row.get("code", "").strip().lower() or None
        names = {lang: row.get(f"name_{lang}", "").strip() for lang in ("ru", "uz", "en")}
        result = RowPlan(line=line, code=code, name=names["ru"], action="error")
        errors = result.errors
        values: dict[str, AttrValue] = {}
        for key, attr in attrs.items():
            text = row.get(key, "").strip()
            if not text:
                continue
            try:
                values[key] = _attr(attr, text)
            except ValueError:
                errors.append((key, "invalid"))
        active: bool | None = None
        if row.get("active", "").strip():
            try:
                active = _flag(row["active"])
            except ValueError:
                errors.append(("active", "invalid"))
        if any(len(n) > 120 for n in names.values()):
            errors.append(("name", "too_long"))
        if code is not None and code in seen:
            errors.append(("code", "duplicate"))
        if code is not None:
            seen.add(code)
        current = existing.get(code) if code else None
        if code is not None and current is None:
            errors.append(("code", "unknown"))
        if current is None and not names["ru"]:
            errors.append(("name_ru", "required"))
        if current is None and dictionary.closed:
            errors.append(("code", "closed"))
        if current is None and code is None:
            for key, attr in attrs.items():
                if attr.type == "choice" and attr.required and key not in values:
                    errors.append((key, "required"))
        if errors:
            plans.append(result)
            continue
        if current is None:
            result.action = "add"
            result.create = {"name": names, "attrs": values}
            plans.append(result)
            continue
        result.code = current.code
        name = {
            "ru": names["ru"] or current.name.ru,
            "uz": names["uz"] or current.name.uz,
            "en": names["en"] or current.name.en,
        }
        patch: dict[str, Any] = {}
        changed: list[str] = []
        for lang in ("ru", "uz", "en"):
            if name[lang] != getattr(current.name, lang):
                changed.append(f"name_{lang}")
        if changed:
            patch["name"] = name
        changed_attrs = {k: v for k, v in values.items() if current.attrs.get(k) != v}
        if changed_attrs:
            patch["attrs"] = changed_attrs
            changed.extend(changed_attrs)
        if active is not None and active != current.active:
            patch["active"] = active
            changed.append("active")
        result.name = name["ru"]
        result.fields = changed
        result.action = "update" if patch else "unchanged"
        result.patch = patch or None
        plans.append(result)
    return plans
