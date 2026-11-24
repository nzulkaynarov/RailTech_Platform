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

#: Шапка таблицы позиций в сетке документа (стандарт документов §6 п. 2): позиция стопкой — артикул над названием.
STACKED: dict[Lang, dict[str, str]] = {
    "ru": {"item": "Артикул · Позиция", "lead": "Срок", "per": "/ 1"},
    "uz": {"item": "Artikul · Pozitsiya", "lead": "Muddat", "per": "/ 1"},
    "en": {"item": "Item No. · Description", "lead": "Lead time", "per": "/ 1"},
}
COLUMNS: dict[Lang, dict[str, str]] = {
    "ru": {"no": "№", "name": "Наименование", "unit": "Ед.", "qty": "Кол-во", "price": "Цена", "amount": "Сумма"},
    "uz": {"no": "№", "name": "Nomi", "unit": "Ölç.", "qty": "Miqdori", "price": "Narxi", "amount": "Summasi"},
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
        "total": "Tölovga jami",
        "paid": "Tölangan",
        "balance": "Tölov qoldiği",
        "words": "Summa söz bilan",
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
    "uz": {"title": "Tölov rekvizitlari", "recipient": "Qabul qiluvçi", "inn": "STIR", "purpose": "Tölov maqsadi"},
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
    # Сетка документа (стандарт §6 п. 2): позиция стопкой — артикул (моно), характеристики, примечание курсивом, срок.
    article: str = ""
    details: Sequence[str] = ()
    note: str = ""
    lead: str = ""


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


def _note(*parts: Node | str) -> Node:
    node = _para(*parts)
    node["attrs"] = {"variant": "note"}
    return node


def _code(value: str) -> Node:
    return {"type": "text", "text": value, "marks": [{"type": "code"}]}


def _cell(value: str, *, header: bool = False, numeric: bool = False, bold: bool = False) -> Node:
    # Пустая ячейка (нет единицы и т. п.) — пустой абзац: пустой текстовый узел контракт тела не допускает.
    para = _para(_text(value, bold=bold)) if value else _para()
    node: Node = {"type": "tableHeader" if header else "tableCell", "content": [para]}
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


def _amount(value: Decimal, lang: Lang) -> str:
    """Сумма сетки документа: без дробной части, если её нет («147 000 000»), иначе с двумя знаками."""
    return format_number(value, lang, decimals=0 if value == value.to_integral_value() else 2)


def _stacked_cell(line: Line) -> Node:
    content: list[Node] = []
    if line.article:
        content.append(_note(_code(line.article)))
    content.append(_para(line.name))
    content += [_note(detail) for detail in line.details if detail.strip()]
    if line.note:
        content.append(_note(_text(line.note, bold=False) | {"marks": [{"type": "italic"}]}))
    return {"type": "tableCell", "content": content}


def _numeric(*paragraphs: Node) -> Node:
    return {"type": "tableCell", "attrs": {"numeric": True}, "content": list(paragraphs)}


def stacked_items_table(lines: Sequence[Line], currency: str, lang: Lang) -> list[Node]:
    """Таблица позиций сетки документа: №, позиция стопкой, срок (если есть), количество с единицей, цена «/ 1 ед.» и
    сумма — без НДС (стандарт документов §6 п. 2)."""
    label = COLUMNS[lang]
    stacked = STACKED[lang]
    ccy = currency_label(currency, lang)
    with_lead = any(line.lead for line in lines)
    header = [
        _cell(label["no"], header=True),
        _cell(stacked["item"], header=True),
        *([_cell(stacked["lead"], header=True, numeric=True)] if with_lead else []),
        _cell(label["qty"], header=True, numeric=True),
        _cell(f"{label['price']}, {ccy}", header=True, numeric=True),
        _cell(f"{label['amount']}, {ccy}", header=True, numeric=True),
    ]
    rows = [{"type": "tableRow", "content": header}]
    for number, line in enumerate(lines, start=1):
        unit = f" {line.unit}" if line.unit else ""
        price = [_para(_amount(line.price, lang))]
        if line.unit:
            price.append(_note(f"{stacked['per']} {line.unit}"))
        cells = [
            _cell(str(number)),
            _stacked_cell(line),
            *([_cell(line.lead or "—", numeric=True)] if with_lead else []),
            _cell(_qty(line.quantity, lang) + unit, numeric=True),
            _numeric(*price),
            _cell(_amount(line.amount, lang), numeric=True),
        ]
        rows.append({"type": "tableRow", "content": cells})
    widths = [5, 43, 9, 12, 16, 15] if with_lead else [5, 50, 13, 16, 16]
    return [{"type": "table", "attrs": {"columnWidths": widths, "variant": "grid"}, "content": rows}]


def grid_totals_block(totals: Totals, currency: str, lang: Lang, *, total_label: str | None = None) -> list[Node]:
    """Итоги сетки документа: справа 75 мм; строка «К оплате» выделена; сумма прописью — примечанием под ней."""
    label = TOTALS[lang]
    ccy = currency_label(currency, lang)

    def row(name: str, value: Decimal, *, emphasis: bool = False) -> Node:
        node: Node = {
            "type": "tableRow",
            "content": [_cell(name, bold=emphasis), _cell(_amount(value, lang), numeric=True, bold=emphasis)],
        }
        if emphasis:
            node["attrs"] = {"emphasis": True}
        return node

    vat = label["vat"] + (f" {format_number(totals.vat_rate, lang, decimals=0)} %" if totals.vat_rate else "")
    rows = [row(label["subtotal"], totals.subtotal), row(vat, totals.vat_amount)]
    if totals.paid:
        rows.append(row(label["paid"], totals.paid))
    due = totals.balance if totals.paid and totals.balance is not None else totals.total
    rows.append(row(f"{total_label or label['total']}, {ccy}", due, emphasis=True))
    words = {"type": "tableCell", "attrs": {"colspan": 2}, "content": [_note(amount_in_words(due, currency, lang))]}
    rows.append({"type": "tableRow", "content": [words]})
    return [{"type": "table", "attrs": {"columnWidths": [58, 42], "variant": "totals"}, "content": rows}]


def conditions_block(pairs: Sequence[tuple[str, str]]) -> list[Node]:
    """Условия парами под итогами (стандарт §6 п. 4): метка полужирным, значение; пустое условие не печатается."""
    rows = [
        {"type": "tableRow", "content": [_cell(name, bold=True), _cell(value)]}
        for name, value in pairs
        if value and value.strip()
    ]
    if not rows:
        return []
    return [{"type": "table", "attrs": {"columnWidths": [24, 76], "variant": "plain"}, "content": rows}]


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
