"""Client-facing КП line projection — the confidentiality boundary of the quote document.

The seller's cost/charge structure must never be decomposable from what the buyer receives:
document-level charges are spread INTO each priced line's delivered price, never listed as a
separate «Доп. расходы» row. Both the PDF and its public HTML twin render from here, so the
two surfaces cannot drift apart on this invariant.
"""

from decimal import ROUND_HALF_UP, Decimal

_PENNY = Decimal("0.01")


def _distribute_charges(priced_items, subtotal, charges) -> tuple[dict, dict]:
    """Spread document-level `charges` across the priced lines proportionally to their share of
    `subtotal`. The LAST line absorbs the rounding remainder so the ITEM rows sum EXACTLY to
    quote.total_excl_vat (= subtotal + charges), the pre-VAT base the document taxes.

    Returns ({item_id: line_total}, {item_id: unit_price}).
    """
    projected_line_total: dict = {}
    projected_unit: dict = {}
    allocated = Decimal("0")
    last = len(priced_items) - 1
    for idx, item in enumerate(priced_items):
        base = item.line_total or Decimal("0")
        if charges and subtotal:
            if idx < last:
                share = (charges * base / subtotal).quantize(_PENNY, rounding=ROUND_HALF_UP)
                allocated += share
            else:
                share = charges - allocated  # last line absorbs the remainder → penny-exact Σ
        else:
            share = Decimal("0")
        line_total = base + share
        qty = item.quantity or Decimal("1")
        projected_line_total[item.id] = line_total
        projected_unit[item.id] = (line_total / qty).quantize(_PENNY, rounding=ROUND_HALF_UP) if qty else line_total
    return projected_line_total, projected_unit


def _annotate_section_subtotals(rows: list) -> None:
    """Each SECTION's subtotal = Σ line_total of the ITEM rows below it until the next SECTION
    (its group), plus a count of grouped ITEM rows so an EMPTY section can be dropped. Ungrouped
    ITEM rows above the first SECTION are simply not summed. Mutates `rows` in place."""
    current_section = None
    for row in rows:
        if row["display_type"] == "SECTION":
            current_section = row
            row["_item_count"] = 0
        elif row["display_type"] == "ITEM" and current_section is not None:
            current_section["section_subtotal"] += row["line_total"]
            current_section["_item_count"] += 1


def _keep_row(row) -> bool:
    """Wave C polish: a document should never show an EMPTY structural row. Drop a SECTION that
    groups no ITEM lines (the «НОВЫЙ РАЗДЕЛ — 0,00» artifact) and a NOTE with no text — both
    read as a rendering bug to the client. Count-based, NOT subtotal-based: a section whose real
    lines sum to 0 (all free/included) still groups items and MUST render."""
    if row["display_type"] == "SECTION":
        return row.get("_item_count", 0) > 0
    if row["display_type"] == "NOTE":
        return bool((row.get("imported_raw_name") or "").strip())
    return True


def _section_row(item) -> dict:
    """A group header. `line_total` is 0 so Σ line_total over the rows stays penny-exact;
    `section_subtotal` is filled by the second pass once the group's members are known."""
    return {
        "display_type": "SECTION",
        "imported_raw_name": item.imported_raw_name,
        "line_total": Decimal("0"),
        "section_subtotal": Decimal("0"),
    }


def _note_row(item) -> dict:
    """A free-text note — no price, no number."""
    return {
        "display_type": "NOTE",
        "imported_raw_name": item.imported_raw_name,
        "line_total": Decimal("0"),
    }


def _item_row(item, line_no: int, projected_unit: dict, projected_line_total: dict) -> dict:
    """A priced line carrying ONE all-in delivered price (document charges already spread in).

    NEVER a separate «Доп. расходы» line: a goods-vs-charges breakout would let the buyer
    decompose the seller's cost/charge structure.
    """
    return {
        "display_type": "ITEM",
        "line_no": line_no,
        "product": item.product,
        "imported_raw_name": item.imported_raw_name,
        "mpn": item.mpn,
        "gost_drawing": item.gost_drawing,
        "quantity": item.quantity,
        "unit": item.unit,
        "lead_time_days": item.lead_time_days,
        "final_price_excl_vat": projected_unit.get(item.id, Decimal("0")),
        "line_total": projected_line_total.get(item.id, Decimal("0")),
    }


def client_projection_items(quote) -> list:
    """Client-facing КП rows (Odoo `display_type`) in explicit `position` order, with document-level
    charges distributed proportionally into each priced line's delivered price.

    The list mixes three row kinds (each dict carries `display_type`):
      • ITEM    — a priced line: ONE all-in delivered price (charges spread in). NEVER a separate
                  «Доп. расходы» line — the goods-vs-charges breakout would let the buyer decompose
                  the seller's cost/charge structure (confidentiality).
      • SECTION — a group header (`section_subtotal` = Σ of that section's ITEM line totals, up to
                  the next SECTION). `line_total` is 0 so Σ line_total stays penny-exact.
      • NOTE    — a free-text note (`line_total` 0, no price).
    OPTIONAL lines are excluded here (they are quoted outside the totals — see
    `client_optional_items`).
    """
    from crm.models import QuoteItem

    items = list(quote.items.select_related("product", "frozen_currency").all())  # position order
    # Priced lines the charges distribute across = non-optional ITEM rows only. Sections/notes and
    # optional lines carry no share (sections/notes have no price; optional lines are off-total).
    priced = [it for it in items if it.display_type == QuoteItem.DisplayType.ITEM and not it.is_optional]
    projected_line_total, projected_unit = _distribute_charges(
        priced, quote.subtotal_excl_vat or Decimal("0"), quote.charges_total or Decimal("0")
    )

    rows: list = []
    line_no = 0  # 1-based sequence over PRICED rows only — sections/notes are not numbered.
    for item in items:
        # Optional priced lines are rendered in their own block, not in the main list.
        if item.display_type == QuoteItem.DisplayType.ITEM and item.is_optional:
            continue
        if item.display_type == QuoteItem.DisplayType.SECTION:
            rows.append(_section_row(item))
        elif item.display_type == QuoteItem.DisplayType.NOTE:
            rows.append(_note_row(item))
        else:
            line_no += 1
            rows.append(_item_row(item, line_no, projected_unit, projected_line_total))

    _annotate_section_subtotals(rows)
    return [row for row in rows if _keep_row(row)]


def client_optional_items(quote) -> list:
    """Optional КП lines (is_optional ITEM rows) in `position` order — shown to the buyer with a
    price in a SEPARATE «Опционально» block, but NEVER folded into subtotal/НДС/total. No document
    charges are distributed into them (they are outside the priced offer); the raw per-line price
    and line total are shown as computed by the engine."""
    from crm.models import QuoteItem

    return [
        {
            "product": item.product,
            "imported_raw_name": item.imported_raw_name,
            "mpn": item.mpn,
            "gost_drawing": item.gost_drawing,
            "quantity": item.quantity,
            "unit": item.unit,
            "lead_time_days": item.lead_time_days,
            "final_price_excl_vat": item.final_price_excl_vat,
            "line_total": item.line_total,
        }
        for item in quote.items.select_related("product", "frozen_currency").all()
        if item.display_type == QuoteItem.DisplayType.ITEM and item.is_optional
    ]
