"""CSV для Excel ru: BOM, `;`, запятая в дробях, Ташкент, экранирование формул."""

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.domain.csv_export import Cell, format_cell, render


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "да"),
        (False, "нет"),
        (42, "42"),
        (Decimal("1234.5"), "1234,50"),
        (0.1, "0,10"),
        # 19:30 UTC — 00:30 следующего дня в Ташкенте (UTC+5).
        (datetime(2026, 10, 12, 19, 30, tzinfo=UTC), "13.10.2026 00:30"),
        (date(2026, 1, 2), "02.01.2026"),
        (["rails", "wagons"], "rails, wagons"),
        ("Иван", "Иван"),
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+998901234567", "'+998901234567"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
    ],
)
def test_format_cell(value: Cell, expected: str) -> None:
    assert format_cell(value) == expected


def test_render_bom_semicolon_crlf_and_quoting() -> None:
    lines = list(
        render(["ID", "Имя"], [(1, "ООО «Рельс; и шпалы»"), (2, 'Он сказал "да"\nи ушёл')])
    )
    assert lines[0] == "﻿ID;Имя\r\n"
    assert lines[1] == '1;"ООО «Рельс; и шпалы»"\r\n'
    parsed = list(csv.reader(io.StringIO("".join(lines).removeprefix("﻿")), delimiter=";"))
    assert parsed == [["ID", "Имя"], ["1", "ООО «Рельс; и шпалы»"], ["2", 'Он сказал "да"\nи ушёл']]


def test_render_empty_has_headers_only() -> None:
    assert list(render(["A"], [])) == ["﻿A\r\n"]
