"""Блоки коммерческих документов (план 2026-11-12 п. 2.6): таблица позиций, итоги с НДС и суммой прописью,
платёжные реквизиты — узлами тела контракта (`documents/body.schema.json`), одинаково для КП, договора, счёта и акта.

Домен передаёт данные (позиции, суммы, реквизиты), постоянные подписи («Итого к оплате», шапки таблиц) берутся отсюда на
языке документа — их никто не переводит вручную (исследование 2026-11-11 «Документы и шаблоны» §2). Результат — список
узлов для `render_pdf(..., blocks={"doc.items_table": items_table(...), ...})`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .formatters import amount_in_words, currency_label, format_money, format_number
from .model import Lang, Money

Node = dict[str, Any]

COLUMNS: dict[Lang, dict[str, str]] = {
    "ru": {"no": "№", "name": "Наименование", "unit": "Ед.", "qty": "Кол-во", "price": "Цена", "amount": "Сумма"},
    "uz": {"no": "№", "name": "Nomi", "unit": "Oʻlch.", "qty": "Miqdori", "price": "Narxi", "amount": "Summasi"},
    "en": {"no": "No.", "name": "Description", "unit": "Unit", "qty": "Qty", "price": "Price", "amount": "Amount"},
}
TOTALS: dict[Lang, dict[str, str]] = {
    "ru": {
        "subtotal": "Сумма без НДС",
        "vat": "НДС",
        "total": "Итого к оплате",
        "paid": "Оплачено",
        "balance": "Остаток к оплате",
        "words": "Сумма прописью",
    },
    "uz": {
        "subtotal": "QQSsiz summa",
        "vat": "QQS",
        "total": "Toʻlovga jami",
        "paid": "Toʻlangan",
        "balance": "Toʻlov qoldigʻi",
        "words": "Summa soʻz bilan",
    },
    "en": {
        "subtotal": "Subtotal excl. VAT",
        "vat": "VAT",
        "total": "Total due",
        "paid": "Paid",
        "balance": "Balance due",
        "words": "Amount in words",
    },
}
PAYMENT: dict[Lang, dict[str, str]] = {
    "ru": {"title": "Платёжные реквизиты", "recipient": "Получатель", "inn": "ИНН", "purpose": "Назначение платежа"},
    "uz": {"title": "Toʻlov rekvizitlari", "recipient": "Qabul qiluvchi", "inn": "STIR", "purpose": "Toʻlov maqsadi"},
    "en": {"title": "Payment details", "recipient": "Beneficiary", "inn": "TIN", "purpose": "Payment reference"},
}


@dataclass(frozen=True)
class Line:
    """Строка таблицы позиций: цены и сумма — без НДС, как в документах ERP."""

    name: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    unit: str = ""


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    vat_rate: Decimal | None = None
    paid: Decimal | None = None
    balance: Decimal | None = None


def _text(value: str, *, bold: bool = False) -> Node:
    node: Node = {"type": "text", "text": value}
    if bold:
        node["marks"] = [{"type": "bold"}]
    return node


def _para(*parts: Node | str) -> Node:
    content = [_text(p) if isinstance(p, str) else p for p in parts if p != ""]
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _cell(value: str, *, header: bool = False, numeric: bool = False, bold: bool = False) -> Node:
    node: Node = {"type": "tableHeader" if header else "tableCell", "content": [_para(_text(value, bold=bold))]}
    if numeric:
        node["attrs"] = {"numeric": True}
    return node


def _qty(value: Decimal, lang: Lang) -> str:
    """Количество без лишних нулей: «2», «2,5», «0,125»."""
    exponent = value.normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return format_number(value, lang, decimals=min(decimals, 3))


def items_table(lines: Sequence[Line], currency: str, lang: Lang, *, with_unit: bool = True) -> list[Node]:
    """Таблица позиций с повтором шапки на каждой странице; суммы — в валюте документа без НДС."""
    label = COLUMNS[lang]
    ccy = currency_label(currency, lang)
    head = [label["no"], label["name"], *([label["unit"]] if with_unit else []), label["qty"]]
    header = [_cell(h, header=True, numeric=(h == label["qty"])) for h in head] + [
        _cell(f"{label['price']}, {ccy}", header=True, numeric=True),
        _cell(f"{label['amount']}, {ccy}", header=True, numeric=True),
    ]
    rows = [{"type": "tableRow", "content": header}]
    for number, line in enumerate(lines, start=1):
        cells = [_cell(str(number)), _cell(line.name)]
        if with_unit:
            cells.append(_cell(line.unit))
        cells += [
            _cell(_qty(line.quantity, lang), numeric=True),
            _cell(format_number(line.price, lang), numeric=True),
            _cell(format_number(line.amount, lang), numeric=True),
        ]
        rows.append({"type": "tableRow", "content": cells})
    widths = [6, 46, 8, 10, 15, 15] if with_unit else [6, 48, 10, 18, 18]
    return [{"type": "table", "attrs": {"columnWidths": widths, "variant": "grid"}, "content": rows}]


def totals_block(totals: Totals, currency: str, lang: Lang) -> list[Node]:
    """Итоги справа: без НДС, НДС (со ставкой), к оплате; оплачено и остаток — если переданы; сумма прописью."""
    label = TOTALS[lang]

    def row(name: str, value: Decimal, *, bold: bool = False) -> Node:
        return {
            "type": "tableRow",
            "content": [
                _cell(f"{name}:", bold=bold),
                _cell(format_money(Money(value, currency), lang), numeric=True, bold=bold),
            ],
        }

    vat = label["vat"] + (f" {format_number(totals.vat_rate, lang, decimals=0)}%" if totals.vat_rate else "")
    rows = [
        row(label["subtotal"], totals.subtotal),
        row(vat, totals.vat_amount),
        row(label["total"], totals.total, bold=True),
    ]
    if totals.paid:
        rows.append(row(label["paid"], totals.paid))
        rows.append(row(label["balance"], totals.balance if totals.balance is not None else totals.total - totals.paid))
    return [
        {"type": "table", "attrs": {"columnWidths": [60, 40], "variant": "totals"}, "content": rows},
        _para(_text(f"{label['words']}: ", bold=True), amount_in_words(totals.total, currency, lang)),
    ]


def payment_requisites(
    lang: Lang, *, recipient: str, inn: str = "", bank_lines: Sequence[str] = (), purpose: str = ""
) -> list[Node]:
    """Платёжные реквизиты счёта: получатель с ИНН, банк строками, назначение платежа."""
    label = PAYMENT[lang]
    nodes: list[Node] = [
        {"type": "heading", "attrs": {"level": 3}, "content": [_text(label["title"])]},
        _para(_text(f"{label['recipient']}: ", bold=True), recipient + (f" · {label['inn']} {inn}" if inn else "")),
    ]
    nodes += [_para(line) for line in bank_lines if line.strip()]
    if purpose:
        nodes.append(_para(_text(f"{label['purpose']}: ", bold=True), purpose))
    return nodes
