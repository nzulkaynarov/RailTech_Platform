"""Golden-кейсы ERP (`evals/golden/*.yaml`) и загрузчик со строгой проверкой формы.

Два набора по образцу CRM (`apps/crm/backend/evals`):
- `intake.yaml` — разбор запроса: свободный текст (`kind: text`, функция compose) или CSV-файл
  (`kind: csv`, функция intake) → ожидаемые строки (ключевые слова имени, количество, единица);
- `match.yaml` — сопоставление: строки запроса + шорт-листы кандидатов каталога → ожидаемый
  лучший `product_id` (или `null` — «ничего не подходит»).

Данные нейтральные (товары и услуги любого бизнеса), без реальных компаний. Кейс с ошибкой
формы — ValueError при загрузке: битый golden не должен тихо превращаться в «зелёный» прогон.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GOLDEN_DIR = Path(__file__).parent / "golden"
_CASE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ExpectedLine:
    name_any: tuple[str, ...]
    quantity: int | None = None
    unit_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntakeCase:
    id: str
    kind: str  # text | csv
    input: str
    lines: tuple[ExpectedLine, ...]
    max_extra_lines: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EvalCandidate:
    id: int
    name: str
    sku: str = ""
    gost_drawing: str = ""


@dataclass(frozen=True)
class MatchLine:
    name: str
    candidates: tuple[EvalCandidate, ...]
    expect_product_id: int | None
    name_canonical: str = ""
    mpn: str = ""
    gost_drawing: str = ""


@dataclass(frozen=True)
class MatchCase:
    id: str
    lines: tuple[MatchLine, ...]
    tags: tuple[str, ...] = field(default_factory=tuple)


def _require(raw: dict, key: str, kind: type, case_id: str):
    value = raw.get(key)
    if not isinstance(value, kind):
        raise ValueError(f"golden case {case_id!r}: field {key!r} must be {kind.__name__}")
    return value


def _check_keys(raw: dict, allowed: set[str], case_id: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"golden case {case_id!r}: unknown fields {sorted(extra)}")


def _case_id(raw: dict) -> str:
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not _CASE_ID.match(case_id):
        raise ValueError(f"golden case id {case_id!r} must be kebab-case")
    return case_id


def _expected_line(raw: dict, case_id: str) -> ExpectedLine:
    _check_keys(raw, {"name_any", "quantity", "unit_any"}, case_id)
    names = _require(raw, "name_any", list, case_id)
    if not names or not all(isinstance(name, str) and name.strip() for name in names):
        raise ValueError(f"golden case {case_id!r}: name_any must list non-empty strings")
    quantity = raw.get("quantity")
    if quantity is not None and (not isinstance(quantity, int) or quantity < 1):
        raise ValueError(f"golden case {case_id!r}: quantity must be a positive int")
    return ExpectedLine(tuple(names), quantity, tuple(raw.get("unit_any") or ()))


def parse_intake_case(raw: dict) -> IntakeCase:
    case_id = _case_id(raw)
    _check_keys(raw, {"id", "kind", "input", "lines", "max_extra_lines", "tags"}, case_id)
    kind = _require(raw, "kind", str, case_id)
    if kind not in ("text", "csv"):
        raise ValueError(f"golden case {case_id!r}: kind must be text|csv")
    lines = tuple(_expected_line(line, case_id) for line in _require(raw, "lines", list, case_id))
    return IntakeCase(
        id=case_id,
        kind=kind,
        input=_require(raw, "input", str, case_id),
        lines=lines,
        max_extra_lines=int(raw.get("max_extra_lines") or 0),
        tags=tuple(raw.get("tags") or ()),
    )


def _match_line(raw: dict, case_id: str) -> MatchLine:
    _check_keys(raw, {"name", "name_canonical", "mpn", "gost_drawing", "candidates", "expect"}, case_id)
    candidates = tuple(
        EvalCandidate(
            id=_require(c, "id", int, case_id),
            name=_require(c, "name", str, case_id),
            sku=c.get("sku") or "",
            gost_drawing=c.get("gost_drawing") or "",
        )
        for c in _require(raw, "candidates", list, case_id)
    )
    expect = raw.get("expect")
    if expect is not None and expect not in {c.id for c in candidates}:
        raise ValueError(f"golden case {case_id!r}: expect {expect} is not among the line's candidates")
    return MatchLine(
        name=_require(raw, "name", str, case_id),
        candidates=candidates,
        expect_product_id=expect,
        name_canonical=raw.get("name_canonical") or "",
        mpn=raw.get("mpn") or "",
        gost_drawing=raw.get("gost_drawing") or "",
    )


def parse_match_case(raw: dict) -> MatchCase:
    case_id = _case_id(raw)
    _check_keys(raw, {"id", "lines", "tags"}, case_id)
    lines = tuple(_match_line(line, case_id) for line in _require(raw, "lines", list, case_id))
    return MatchCase(id=case_id, lines=lines, tags=tuple(raw.get("tags") or ()))


def _load(name: str, parser, directory: Path):
    raw_cases = yaml.safe_load((directory / name).read_text(encoding="utf-8")) or []
    cases = [parser(raw) for raw in raw_cases]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name}: duplicate case ids")
    return cases


def load_intake_cases(directory: Path = GOLDEN_DIR) -> list[IntakeCase]:
    return _load("intake.yaml", parse_intake_case, directory)


def load_match_cases(directory: Path = GOLDEN_DIR) -> list[MatchCase]:
    return _load("match.yaml", parse_match_case, directory)
