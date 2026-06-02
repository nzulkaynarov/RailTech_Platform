from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# Parameter dataclasses — reduce long argument lists (Sprint 4b).
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class PaymentData:
    """Groups payment-related parameters for record_payment()."""

    invoice_id: int
    amount: object  # Decimal-coercible (str, int, float, Decimal)
    paid_at: object  # date or datetime
    method: str = "BANK_TRANSFER"
    reference: str = ""
    proof_file: Optional[object] = None
    manual: bool = True


@dataclass
class BidSubmission:
    """Groups supplier bid parameters for submit_supplier_bid()."""

    deal_id: int
    supplier_id: int
    items: list = field(default_factory=list)
    notes: str = ""
    lead_time_days: Optional[int] = None
    currency_id: Optional[int] = None
