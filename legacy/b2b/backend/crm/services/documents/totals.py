"""The uniform VAT bridge shared by every transactional PDF (КП / договор / инвойс / акт)."""


def document_totals(
    *,
    ccy: str,
    vat_rate=None,
    subtotal=None,
    vat_amount=None,
    total=None,
    amount_paid=None,
    balance_due=None,
) -> dict:
    """The uniform «Сумма без НДС → НДС X% → Итого к оплате» bridge for EVERY transactional PDF
    (КП / договор / инвойс / акт). D1: the four documents used three different totals formats
    («3 разных формата итогов НДС»); this single builder + the shared _totals_block.html partial
    give them one identical block.

    Pass whichever figures the model actually stores — the rest are derived:
      • gross `total` + `vat_rate` only (contract) → subtotal = total / (1 + rate/100);
      • `subtotal` + `vat_amount` (invoice/act) → total and the effective rate are derived.
    """
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

    def _dec(value):
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    subtotal_d, vat_d, total_d, rate = _dec(subtotal), _dec(vat_amount), _dec(total), _dec(vat_rate)
    if subtotal_d is None and total_d is not None:
        if rate and rate > 0:
            subtotal_d = (total_d / (Decimal(1) + rate / Decimal(100))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            subtotal_d = total_d
    if vat_d is None and total_d is not None and subtotal_d is not None:
        vat_d = total_d - subtotal_d
    if total_d is None and subtotal_d is not None:
        total_d = subtotal_d + (vat_d or Decimal(0))
    if (rate is None or rate == 0) and subtotal_d and vat_d and subtotal_d > 0:
        rate = (vat_d / subtotal_d * Decimal(100)).quantize(Decimal("1"), ROUND_HALF_UP)
    return {
        "ccy": ccy or "UZS",
        "vat_rate": rate or Decimal(0),
        "subtotal": subtotal_d,
        "vat_amount": vat_d,
        "total": total_d,
        "amount_paid": _dec(amount_paid),
        "balance_due": _dec(balance_due),
    }
