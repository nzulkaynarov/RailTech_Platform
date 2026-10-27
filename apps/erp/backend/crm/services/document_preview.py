"""Предпросмотр шаблона на каркасе своего вида и с образцами блоков (B-012, W15-H8).

Редактор шаблона показывает не общий каркас «Образец документа» с пунктирными заглушками, а то, как
выглядит настоящий документ этого вида: договор — со сторонами и «Договор поставки», счёт — со «Счётом на
оплату» и плательщиком, акт — с «Актом приёма-передачи». Структурные блоки собираются теми же partials
`crm/blocks/*`, что и при печати, но на вымышленных данных (`SimpleNamespace`, БД не трогаем). Вид без
своего каркаса (письмо, рапорт, произвольный) остаётся на общем каркасе. Блок чужого вида в теле остаётся
подписанной пунктирной заглушкой.
"""

import datetime
from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.utils import timezone

#: Виды с собственным каркасом и образцами блоков: код вида -> шаблон каркаса.
FRAMES = {
    "CONTRACT": "crm/contract_pdf_templated.html",
    "INVOICE": "crm/invoice_pdf_templated.html",
    "ACT": "crm/act_pdf_templated.html",
}

_CCY = "UZS"
_VAT_RATE = Decimal("12")


class _Items:
    """`invoice.items.all()` для partial-блока акта."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _demo_items() -> list:
    rows = (
        ("Стрелочный привод СП-6", Decimal("2"), Decimal("4200000")),
        ("Монтажные работы", Decimal("1"), Decimal("1500000")),
    )
    return [
        SimpleNamespace(
            description=name,
            product=SimpleNamespace(name=name),
            imported_raw_name="",
            quantity=qty,
            unit=None,
            unit_price_excl_vat=price,
            final_price_excl_vat=price,
            line_total_excl_vat=qty * price,
            line_total=qty * price,
        )
        for name, qty, price in rows
    ]


def _demo_totals(items: list) -> dict:
    from .documents.totals import document_totals

    subtotal = sum((row.line_total for row in items), Decimal(0))
    vat = (subtotal * _VAT_RATE / Decimal(100)).quantize(Decimal("0.01"))
    return document_totals(ccy=_CCY, vat_rate=_VAT_RATE, subtotal=subtotal, vat_amount=vat, total=subtotal + vat)


def _frame(kind_code: str, company, brand: dict, now: datetime.datetime) -> tuple[dict, dict, dict, str]:
    """(контекст каркаса, блоки, скаляры, шаблон каркаса) для вида."""
    from . import document_blocks as blocks_module
    from .document_blocks import format_document_date

    buyer = SimpleNamespace(
        name="ООО Пример",
        inn="301234567",
        legal_address="г. Ташкент, ул. Образцовая, 1",
        bank_account="",
        mfo="",
        phone="",
    )
    seller = brand.get("seller")
    profile = brand.get("seller_profile")
    items = _demo_items()
    totals = _demo_totals(items)
    deal = SimpleNamespace(company=buyer, contact=None)
    contract = SimpleNamespace(
        number="ДГ-2026-00007",
        created_at=now,
        valid_from=None,
        valid_until=None,
        notes="",
        total_amount=totals["total"],
        quote=None,
        quote_id=None,
        deal=deal,
        wording_selections=None,
        manager_signer=None,
        client_signer=None,
    )
    date = format_document_date(now)
    from crm.templatetags.document_format import money

    if kind_code == "CONTRACT":
        blocks = blocks_module.contract_block_values(
            contract, items, totals, _CCY, seller=seller, seller_profile=profile
        )
        scalars = {
            "doc.number": contract.number,
            "doc.date": date,
            "doc.total": money(totals["total"], _CCY),
            "doc.currency": _CCY,
            "doc.vat_rate": str(int(_VAT_RATE)),
            "doc.delivery_terms": blocks_module._contract_delivery_terms(None),
            "doc.valid_from": "с даты его подписания обеими Сторонами",
            "doc.valid_until": "до полного исполнения Сторонами своих обязательств",
        }
        context = {"contract": contract, "company": buyer}
    elif kind_code == "INVOICE":
        invoice = SimpleNamespace(
            number="СЧ-2026-00012",
            issued_at=now,
            created_at=now,
            due_date=(now + datetime.timedelta(days=10)).date(),
            contract=contract,
            notes="",
            vat_amount=totals["vat_amount"],
            total_incl_vat=totals["total"],
            items=_Items(items),
        )
        blocks = blocks_module.invoice_block_values(invoice, items, totals, _CCY, seller=seller, seller_profile=profile)
        scalars = {
            "doc.number": invoice.number,
            "doc.date": date,
            "doc.total": money(totals["total"], _CCY),
            "doc.currency": _CCY,
        }
        context = {"invoice": invoice, "company": buyer, "contact": None}
    else:  # ACT
        invoice = SimpleNamespace(number="СЧ-2026-00012", issued_at=now, created_at=now, items=_Items(items))
        act = SimpleNamespace(
            number="АКТ-2026-00005",
            issued_at=now,
            created_at=now,
            deal_id=1024,
            deal=deal,
            contract=contract,
            invoice=invoice,
            total_amount=totals["total"],
            wording_selections=None,
            issuer_signer=None,
            acceptor_signer=None,
        )
        blocks = blocks_module.act_block_values(act, invoice, totals, _CCY, seller=seller, seller_profile=profile)
        scalars = {"doc.number": act.number, "doc.date": date, "doc.total": totals["total"]}
        context = {"act": act, "invoice": invoice, "company": buyer, "contact": None, "totals": totals}
    return context, blocks, scalars, FRAMES[kind_code]


def render_kind_preview(company, rendered_body: str, kind_code: str) -> tuple[str, str] | None:
    """(тело с образцами блоков, полный HTML документа на каркасе вида) или None, если у вида нет каркаса."""
    if kind_code not in FRAMES:
        return None
    from .document_blocks import render_document_body
    from .documents import document_brand_context

    brand = document_brand_context(company)
    now = timezone.now()
    context, blocks, scalars, template = _frame(kind_code, company, brand, now)
    body = render_document_body(rendered_body, blocks=blocks, scalars=scalars)
    html = render_to_string(template, {**context, "body_html": body, **brand})
    return body, html
